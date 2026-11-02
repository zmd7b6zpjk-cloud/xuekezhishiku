"""知识库存储层。

设计原则：``vault/`` 里的 Markdown 文件是唯一事实来源，SQLite 只是
可以随时重建的索引。因此删掉 ``data/kb.sqlite3`` 不会丢任何知识，
外部编辑器（Obsidian / VS Code / 记事本）修改文件后也会被自动同步。
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import frontmatter as fm

EMPTY_DISCIPLINE = "未分类"
WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
HASHTAG_RE = re.compile(r"(?<![\w#&])#([0-9A-Za-z_\-\u4e00-\u9fff]{2,24})")
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_FENCE_RE = re.compile(r"```.*?```", re.S)


class KBError(Exception):
    """带 HTTP 状态码的业务错误。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def _norm_date(value, fallback_ts: float | None = None) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
    text = value.strip() if isinstance(value, str) else ""
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?", text)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)),
                int(match.group(4) or 0), int(match.group(5) or 0),
            ).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_ts if fallback_ts is not None else time.time()).strftime("%Y-%m-%d %H:%M")


def _safe_name(name: str) -> str:
    text = _ILLEGAL.sub("_", str(name)).strip().rstrip(". ")
    if not text:
        text = "未命名"
    if text.split(".")[0].upper() in _RESERVED:
        text = "_" + text
    return text[:100]


def _word_count(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text or ""))
    latin = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    return cjk + latin


def _split_query(query: str) -> tuple[list[str], list[str], list[str]]:
    terms: list[str] = []
    tags: list[str] = []
    disciplines: list[str] = []
    for token in (query or "").split():
        if token.startswith("#") and len(token) > 1:
            tags.append(token[1:])
        elif token.startswith("@") and len(token) > 1:
            disciplines.append(token[1:])
        elif token.lower().startswith("tag:") and len(token) > 4:
            tags.append(token[4:])
        else:
            terms.append(token)
    return terms, tags, disciplines


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.vault = self.root / "vault"
        self.inbox = self.root / "inbox"
        self.attachments = self.root / "attachments"
        self.data = self.root / "data"
        self.backups = self.root / "backups"
        self.trash = self.data / "trash"
        self.archive = self.data / "ingested"
        for directory in (self.vault, self.inbox, self.attachments, self.data, self.backups, self.trash, self.archive):
            directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data / "kb.sqlite3"
        self._lock = threading.RLock()
        self._warned: set[str] = set()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self.fts_ok = True
        self._init_schema()
        self._last_sync = 0.0
        self.sync(force=True)

    # ------------------------------------------------------------------ 索引
    def _init_schema(self) -> None:
        db = self._db
        db.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                title TEXT PRIMARY KEY,
                discipline TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                body TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL,
                mtime_ns INTEGER NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 0,
                rev TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL DEFAULT '',
                updated TEXT NOT NULL DEFAULT '',
                links TEXT NOT NULL DEFAULT '[]',
                words INTEGER NOT NULL DEFAULT 0
            )"""
        )
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_path ON entries(path)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_entries_discipline ON entries(discipline)")
        try:
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts "
                "USING fts5(title, body, tags, tokenize='trigram')"
            )
        except sqlite3.Error:
            self.fts_ok = False
        db.execute("CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)")
        db.execute("PRAGMA user_version=1")
        db.commit()

    def _warn(self, message: str) -> None:
        if message not in self._warned:
            self._warned.add(message)
            print(f"[知识库] {message}")

    def sync(self, force: bool = False) -> int:
        """把磁盘上变化的 Markdown 同步进索引，返回变化条数。"""
        with self._lock:
            now = time.time()
            if not force and now - self._last_sync < 1.0:
                return 0
            self._last_sync = now
            files: dict[str, Path] = {}
            for path in self.vault.rglob("*.md"):
                parts = path.relative_to(self.vault).parts
                if any(part.startswith(".") for part in parts):
                    continue
                files[path.relative_to(self.vault).as_posix()] = path
            rows = {row["path"]: row for row in self._db.execute("SELECT rowid, path, mtime_ns, size FROM entries")}
            changed = 0
            for rel, path in sorted(files.items()):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                old = rows.get(rel)
                if old and old["mtime_ns"] == stat.st_mtime_ns and old["size"] == stat.st_size:
                    continue
                try:
                    entry = self._read_file(path)
                except Exception as exc:  # noqa: BLE001 - 单个坏文件不能拖垮服务
                    self._warn(f"跳过无法解析的文件 {rel}：{exc}")
                    continue
                if self._write_db(entry):
                    changed += 1
            stale = [(rel, rows[rel]["rowid"]) for rel in rows if rel not in files]
            for rel, rowid in stale:
                self._db.execute("DELETE FROM entries WHERE rowid=?", (rowid,))
                if self.fts_ok:
                    self._db.execute("DELETE FROM entries_fts WHERE rowid=?", (rowid,))
                self._warn(f"索引中移除已删除的文件 {rel}")
                changed += 1
            if changed:
                self._db.commit()
            return changed

    def _read_file(self, path: Path) -> dict:
        text = path.read_text(encoding="utf-8-sig")
        meta, body = fm.parse(text)
        stat = path.stat()
        title = str(meta.get("title") or path.stem).strip() or path.stem
        discipline = str(meta.get("discipline") or "").strip() or self._discipline_from_path(path)
        tags = self._normalize_tags(meta.get("tags"))
        links = self._extract_links(body)
        extra_links = self._normalize_links(meta.get("links"))
        for link in extra_links:
            if link not in links:
                links.append(link)
        return {
            "title": title,
            "discipline": discipline,
            "tags": tags,
            "body": (body or "").strip("\n"),
            "path": path.relative_to(self.vault).as_posix(),
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "rev": self._rev(text),
            "created": _norm_date(meta.get("created"), stat.st_ctime),
            "updated": _norm_date(meta.get("updated"), stat.st_mtime),
            "links": links,
            "words": _word_count((body or "")),
        }

    def _discipline_from_path(self, path: Path) -> str:
        rel = path.relative_to(self.vault)
        if len(rel.parts) > 1:
            return rel.parts[0]
        return EMPTY_DISCIPLINE

    @staticmethod
    def _rev(text: str) -> str:
        import hashlib

        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

    def _write_db(self, entry: dict) -> bool:
        db = self._db
        row = db.execute("SELECT rowid, path FROM entries WHERE title=?", (entry["title"],)).fetchone()
        if row is not None and row["path"] != entry["path"]:
            self._warn(f"同名卡片冲突：{entry['path']} 与 {row['path']}，保留先出现的")
            return False
        values = (
            entry["discipline"], json.dumps(entry["tags"], ensure_ascii=False), entry["body"],
            entry["path"], entry["mtime_ns"], entry["size"], entry["rev"], entry["created"],
            entry["updated"], json.dumps(entry["links"], ensure_ascii=False), entry["words"],
        )
        if row is not None:
            rowid = row["rowid"]
            db.execute(
                "UPDATE entries SET discipline=?, tags=?, body=?, path=?, mtime_ns=?, size=?, rev=?, "
                "created=?, updated=?, links=?, words=? WHERE rowid=?",
                values + (rowid,),
            )
            if self.fts_ok:
                db.execute("DELETE FROM entries_fts WHERE rowid=?", (rowid,))
        else:
            cursor = db.execute(
                "INSERT INTO entries(title, discipline, tags, body, path, mtime_ns, size, rev, created, "
                "updated, links, words) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (entry["title"],) + values,
            )
            rowid = cursor.lastrowid
        if self.fts_ok:
            try:
                db.execute(
                    "INSERT INTO entries_fts(rowid, title, body, tags) VALUES(?,?,?,?)",
                    (rowid, entry["title"], entry["body"], " ".join(entry["tags"])),
                )
            except sqlite3.Error:
                pass
        return True

    # ------------------------------------------------------------------ 查询
    def _titles(self) -> list[str]:
        return [row["title"] for row in self._db.execute("SELECT title FROM entries")]

    def _exists(self, title: str) -> bool:
        target = title.strip().casefold()
        return any(existing.casefold() == target for existing in self._titles())

    def _find_row(self, title: str):
        row = self._db.execute("SELECT * FROM entries WHERE title=?", (title,)).fetchone()
        if row is not None:
            return row
        target = (title or "").strip().casefold()
        for candidate in self._db.execute("SELECT * FROM entries"):
            if candidate["title"].casefold() == target:
                return candidate
        return None

    def get(self, title: str) -> dict:
        with self._lock:
            self.sync()
            row = self._find_row(title)
            if row is None:
                raise KBError("卡片不存在", 404)
            return self._entry_dict(row, full=True)

    def _entry_dict(self, row, full: bool = False) -> dict:
        tags = json.loads(row["tags"] or "[]")
        links = json.loads(row["links"] or "[]")
        data = {
            "title": row["title"],
            "discipline": row["discipline"],
            "tags": tags,
            "created": row["created"],
            "updated": row["updated"],
            "words": row["words"],
            "path": row["path"],
            "rev": row["rev"],
            "links": links,
        }
        if full:
            data["body"] = row["body"]
            titles = set(self._titles())
            data["links_resolved"] = [link for link in links if link in titles]
            data["dangling"] = [link for link in links if link not in titles]
            data["backlinks"] = self._backlinks(row["title"])
            data["related"] = self._related(row["title"], tags, row["discipline"])
        return data

    def _backlinks(self, title: str) -> list[str]:
        result = []
        for row in self._db.execute("SELECT title, links FROM entries"):
            if title in json.loads(row["links"] or "[]"):
                result.append(row["title"])
        return sorted(result)

    def _related(self, title: str, tags: list[str], discipline: str, limit: int = 6) -> list[dict]:
        tag_set = set(tags)
        scored = []
        for row in self._db.execute("SELECT title, discipline, tags FROM entries WHERE title<>?", (title,)):
            row_tags = set(json.loads(row["tags"] or "[]"))
            shared = row_tags & tag_set
            if not shared and row["discipline"] != discipline:
                continue
            score = len(shared) * 3 + (1 if row["discipline"] == discipline else 0)
            reason = "共同标签：" + "、".join(sorted(shared)[:2]) if shared else "同学科"
            scored.append((score, row["title"], reason))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [{"title": item[1], "reason": item[2]} for item in scored[:limit]]

    def _fts_candidates(self, terms: list[str]) -> set[str] | None:
        if not self.fts_ok:
            return None
        fts_terms = [term for term in terms if len(term) >= 3]
        if not fts_terms:
            return None
        match = " AND ".join('"' + term.replace('"', '""') + '"' for term in fts_terms)
        try:
            rows = self._db.execute(
                "SELECT e.title FROM entries_fts f JOIN entries e ON e.rowid=f.rowid WHERE f MATCH ?",
                (match,),
            ).fetchall()
        except sqlite3.Error:
            return None
        return {row["title"] for row in rows}

    def query(self, q: str = "", discipline: str = "", tag: str = "", limit: int = 300, offset: int = 0) -> dict:
        with self._lock:
            self.sync()
            terms, tag_filters, disc_filters = _split_query(q)
            if discipline:
                disc_filters.append(discipline)
            if tag:
                tag_filters.append(tag)
            rows = self._db.execute("SELECT * FROM entries").fetchall()
            candidates = self._fts_candidates(terms)
            items = []
            for row in rows:
                summary = self._summary(row, terms)
                if disc_filters and not any(summary["discipline"].casefold() == item.casefold() for item in disc_filters):
                    continue
                if tag_filters and not all(
                    any(existing.casefold() == wanted.casefold() for existing in summary["tags"])
                    for wanted in tag_filters
                ):
                    continue
                if candidates is not None and row["title"] not in candidates:
                    continue
                if terms:
                    haystack = (row["title"] + "\n" + row["body"] + "\n" + " ".join(summary["tags"])).casefold()
                    if not all(term.casefold() in haystack for term in terms):
                        continue
                    summary["score"] = self._score(row, terms)
                else:
                    summary["score"] = 0
                items.append(summary)
            items.sort(key=lambda item: item["updated"], reverse=True)
            items.sort(key=lambda item: -item["score"])
            total = len(items)
            page = items[offset: offset + limit] if limit else items[offset:]
            return {"items": page, "total": total, "query": q}

    @staticmethod
    def _score(row, terms: list[str]) -> float:
        title = row["title"].casefold()
        body = row["body"].casefold()
        tags = " ".join(json.loads(row["tags"] or "[]")).casefold()
        score = 0.0
        for term in terms:
            needle = term.casefold()
            if needle in title:
                score += 14
                if title == needle:
                    score += 10
                elif title.startswith(needle):
                    score += 4
            if needle in tags:
                score += 6
            score += min(body.count(needle), 8) * 1.5
        return round(score, 2)

    def _summary(self, row, terms: list[str]) -> dict:
        tags = json.loads(row["tags"] or "[]")
        return {
            "title": row["title"],
            "discipline": row["discipline"],
            "tags": tags,
            "created": row["created"],
            "updated": row["updated"],
            "words": row["words"],
            "path": row["path"],
            "excerpt": self._excerpt(row["body"], terms),
            "score": 0,
        }

    def _excerpt(self, body: str, terms: list[str], width: int = 130) -> str:
        text = _FENCE_RE.sub(" ", body or "")
        text = _IMG_RE.sub(" ", text)
        text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
        text = _MD_LINK_RE.sub(r"\1", text)
        text = re.sub(r"[#>*`~]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""
        low = text.casefold()
        index = -1
        for term in terms:
            found = low.find(term.casefold())
            if found != -1 and (index == -1 or found < index):
                index = found
        if index == -1:
            return text[:width] + ("…" if len(text) > width else "")
        start = max(0, index - 45)
        end = min(len(text), index + width)
        return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")

    def list_all(self, limit: int = 500) -> list[dict]:
        return self.query(limit=limit)["items"]

    # ------------------------------------------------------------------ 写入
    def create(self, title: str, body: str = "", discipline: str = "", tags=None,
               created: str | None = None) -> dict:
        with self._lock:
            self.sync()
            title = self._clean_title(title)
            if self._exists(title):
                raise KBError(f"卡片「{title}」已经存在", 409)
            discipline = self._clean_discipline(discipline)
            tag_list = self._normalize_tags(tags)
            stamp = _now()
            meta = {
                "title": title,
                "discipline": discipline,
                "tags": tag_list,
                "created": _norm_date(created, time.time()) if created else stamp,
                "updated": stamp,
            }
            path = self._path_for(discipline, title)
            if path.exists():
                raise KBError(f"文件已存在：{path.relative_to(self.root)}", 409)
            self._write_file(path, meta, body)
            entry = self._read_file(path)
            self._write_db(entry)
            self._db.commit()
            return self.get(title)

    def update(self, old_title: str, title: str | None = None, body: str | None = None,
               discipline: str | None = None, tags=None) -> dict:
        with self._lock:
            self.sync()
            row = self._find_row(old_title)
            if row is None:
                raise KBError("卡片不存在", 404)
            old = row["title"]
            new_title = self._clean_title(title) if title is not None else old
            if new_title != old and self._exists(new_title):
                raise KBError(f"卡片「{new_title}」已经存在", 409)
            new_body = row["body"] if body is None else body
            new_discipline = self._clean_discipline(discipline) if discipline is not None else row["discipline"]
            new_tags = self._normalize_tags(tags) if tags is not None else json.loads(row["tags"] or "[]")
            old_rowid = self._db.execute("SELECT rowid FROM entries WHERE title=?", (old,)).fetchone()["rowid"]
            old_path = self.vault / row["path"]
            new_path = self._path_for(new_discipline, new_title)
            if new_path != old_path and new_path.exists():
                raise KBError(f"目标文件已存在：{new_path.name}", 409)
            meta = {
                "title": new_title,
                "discipline": new_discipline,
                "tags": new_tags,
                "created": row["created"],
                "updated": _now(),
            }
            # 保留用户在 Obsidian 等工具里添加的自定义字段
            try:
                existing_meta, _ = fm.parse(old_path.read_text(encoding="utf-8-sig"))
            except OSError:
                existing_meta = {}
            for key, value in existing_meta.items():
                if key not in meta:
                    meta[key] = value
            self._write_file(new_path, meta, new_body)
            if new_path != old_path:
                try:
                    old_path.unlink()
                except OSError:
                    pass
                self._db.execute("DELETE FROM entries WHERE rowid=?", (old_rowid,))
                if self.fts_ok:
                    self._db.execute("DELETE FROM entries_fts WHERE rowid=?", (old_rowid,))
                if new_title != old:
                    self._rewrite_links(old, new_title)
            entry = self._read_file(new_path)
            self._write_db(entry)
            self._db.commit()
            self._last_sync = 0.0
            return self.get(new_title)

    def _rewrite_links(self, old: str, new: str) -> None:
        pattern = re.compile(r"\[\[(" + re.escape(old) + r")(\s*[|#][^\]]*)?\]\]")
        for path in self.vault.rglob("*.md"):
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            if old not in text:
                continue
            updated = pattern.sub(lambda m: f"[[{new}{m.group(2) or ''}]]", text)
            meta, body = fm.parse(updated)
            links = meta.get("links")
            if isinstance(links, list) and old in links:
                meta["links"] = [new if item == old else item for item in links]
                updated = fm.serialize(meta, body)
            if updated != text:
                path.write_text(updated, encoding="utf-8")
                self._warn(f"已更新指向「{new}」的双链：{path.name}")

    def delete(self, title: str) -> dict:
        with self._lock:
            self.sync()
            row = self._find_row(title)
            if row is None:
                raise KBError("卡片不存在", 404)
            rowid = self._db.execute("SELECT rowid FROM entries WHERE title=?", (row["title"],)).fetchone()["rowid"]
            path = self.vault / row["path"]
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = self.trash / f"{stamp}-{path.name}"
            if path.exists():
                shutil.move(str(path), str(destination))
            self._db.execute("DELETE FROM entries WHERE rowid=?", (rowid,))
            if self.fts_ok:
                self._db.execute("DELETE FROM entries_fts WHERE rowid=?", (rowid,))
            self._db.commit()
            self._last_sync = 0.0
            return {"title": row["title"], "trash": destination.relative_to(self.root).as_posix()}

    def quick_capture(self, text: str, discipline: str = "") -> dict:
        text = (text or "").strip()
        if not text:
            raise KBError("内容不能为空")
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        title = re.sub(r"^[#>*\-\s]+", "", first)
        title = re.sub(r"#\S+", "", title).strip()
        if len(title) > 30:
            title = title[:30]
        if not title:
            title = "速记"
        tags = self._hashtags(text)
        return self.create(self._unique_title(title), body=text,
                           discipline=discipline or EMPTY_DISCIPLINE, tags=tags)

    # ------------------------------------------------------------------ 收件箱
    def inbox_files(self) -> list[Path]:
        result = []
        for path in sorted(self.inbox.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".md", ".txt"):
                continue
            if path.name.startswith((".", "_")) or path.name.lower() == "readme.md":
                continue
            result.append(path)
        return result

    def ingest_inbox(self) -> dict:
        added, errors = [], []
        with self._lock:
            self.sync()
            for path in self.inbox_files():
                try:
                    text = path.read_text(encoding="utf-8-sig", errors="replace")
                    meta, body = fm.parse(text)
                    title = self._ingest_title(path, meta, body)
                    discipline = self._clean_discipline(str(meta.get("discipline") or ""))
                    tags = self._normalize_tags(meta.get("tags"))
                    for tag in self._hashtags(body):
                        if tag not in tags:
                            tags.append(tag)
                    final_title = self._unique_title(title)
                    entry = self.create(final_title, body=body, discipline=discipline, tags=tags)
                    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                    shutil.move(str(path), str(self.archive / f"{stamp}-{path.name}"))
                    added.append({"title": entry["title"], "discipline": entry["discipline"], "source": path.name})
                except Exception as exc:  # noqa: BLE001
                    errors.append({"file": path.name, "error": str(exc)})
            return {"added": added, "errors": errors, "remaining": len(self.inbox_files())}

    def _ingest_title(self, path: Path, meta: dict, body: str) -> str:
        if meta.get("title"):
            return self._clean_title(str(meta["title"]))
        for line in body.splitlines():
            if line.strip().startswith("# "):
                return self._clean_title(line.strip()[2:])
        stem = re.sub(r"^\d{4}[-_.]?\d{2}[-_.]?\d{2}[-_. ]*", "", path.stem)
        stem = re.sub(r"^\d{8}[-_. ]*", "", stem)
        stem = stem.replace("_", " ").strip() or "未命名笔记"
        return self._clean_title(stem)

    # ------------------------------------------------------------------ 统计
    def stats(self) -> dict:
        with self._lock:
            self.sync()
            rows = self._db.execute(
                "SELECT title, discipline, tags, body, words, updated, links FROM entries"
            ).fetchall()
            disciplines = Counter(row["discipline"] for row in rows)
            tags: Counter = Counter()
            for row in rows:
                for tag in json.loads(row["tags"] or "[]"):
                    tags[tag] += 1
            edges = set()
            for row in rows:
                for link in json.loads(row["links"] or "[]"):
                    if link != row["title"]:
                        edges.add((row["title"], link))
            recent = [
                {"title": row["title"], "discipline": row["discipline"], "updated": row["updated"]}
                for row in sorted(rows, key=lambda item: item["updated"], reverse=True)[:6]
            ]
            return {
                "cards": len(rows),
                "words": sum(row["words"] for row in rows),
                "links": len(edges),
                "disciplines": [{"name": name, "count": count} for name, count in disciplines.most_common()],
                "tags": [{"name": name, "count": count} for name, count in tags.most_common(30)],
                "tag_total": len(tags),
                "inbox": len(self.inbox_files()),
                "recent": recent,
                "root": str(self.root),
                "vault": str(self.vault),
            }

    def graph(self) -> dict:
        with self._lock:
            self.sync()
            rows = self._db.execute("SELECT title, discipline, tags, links FROM entries").fetchall()
            titles = {row["title"] for row in rows}
            degree: Counter = Counter()
            edges = set()
            for row in rows:
                for link in json.loads(row["links"] or "[]"):
                    if link == row["title"]:
                        continue
                    edges.add((row["title"], link))
                    degree[row["title"]] += 1
                    if link in titles:
                        degree[link] += 1
            nodes = []
            for row in rows:
                nodes.append({
                    "title": row["title"],
                    "discipline": row["discipline"],
                    "tags": json.loads(row["tags"] or "[]"),
                    "degree": degree[row["title"]],
                })
            missing = {}
            for source, target in edges:
                if target not in titles:
                    missing[target] = True
            for title in missing:
                nodes.append({"title": title, "discipline": "待创建", "tags": [], "degree": 0, "missing": True})
            return {
                "nodes": nodes,
                "edges": [{"source": source, "target": target} for source, target in sorted(edges)],
                "total_cards": len(rows),
            }

    def doctor(self) -> dict:
        with self._lock:
            self.sync(force=True)
            rows = self._db.execute("SELECT title, discipline, tags, links, body FROM entries").fetchall()
            titles = {row["title"] for row in rows}
            dangling, untagged, orphans, empty = [], [], [], []
            incoming: Counter = Counter()
            outgoing: dict[str, list[str]] = {}
            for row in rows:
                links = [link for link in json.loads(row["links"] or "[]") if link != row["title"]]
                outgoing[row["title"]] = links
                for link in links:
                    if link in titles:
                        incoming[link] += 1
                    else:
                        dangling.append({"from": row["title"], "to": link})
                if not json.loads(row["tags"] or "[]"):
                    untagged.append(row["title"])
                if not (row["body"] or "").strip():
                    empty.append(row["title"])
            for row in rows:
                if incoming[row["title"]] == 0 and not [link for link in outgoing[row["title"]] if link in titles]:
                    orphans.append(row["title"])
            return {
                "cards": len(rows),
                "dangling": dangling,
                "orphans": sorted(orphans),
                "untagged": sorted(untagged),
                "empty": sorted(empty),
                "ok": not (dangling or orphans or untagged or empty),
            }

    # ------------------------------------------------------------------ 备份
    def backup(self) -> Path:
        with self._lock:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = self.backups / f"kb-{stamp}.zip"
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                for base, prefix in ((self.vault, "vault"), (self.attachments, "attachments"), (self.inbox, "inbox")):
                    for path in base.rglob("*"):
                        if path.is_file():
                            archive.write(path, f"{prefix}/{path.relative_to(base).as_posix()}")
            old = sorted(self.backups.glob("kb-*.zip"))
            for path in old[:-10]:
                try:
                    path.unlink()
                except OSError:
                    pass
            return destination

    def export_zip_bytes(self) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for base, prefix in ((self.vault, "vault"), (self.attachments, "attachments")):
                for path in base.rglob("*"):
                    if path.is_file():
                        archive.write(path, f"{prefix}/{path.relative_to(base).as_posix()}")
        return buffer.getvalue()

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _clean_title(title: str) -> str:
        text = re.sub(r"\s+", " ", str(title or "")).strip()
        if not text:
            raise KBError("标题不能为空")
        if re.search(r"[\[\]|]", text):
            raise KBError("标题中不能包含 [ ] | 这三个字符")
        text = text[:120].strip()
        return text

    @staticmethod
    def _clean_discipline(discipline: str) -> str:
        text = re.sub(r"[\\/:*?\"<>|]", "_", str(discipline or "")).strip()
        text = text.strip(". ")
        return text[:20] or EMPTY_DISCIPLINE

    @staticmethod
    def _normalize_tags(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw = re.split(r"[,，、;；\s]+", value)
        elif isinstance(value, (list, tuple, set)):
            raw = []
            for item in value:
                raw.extend(re.split(r"[,，、;；\s]+", str(item)))
        else:
            raw = [str(value)]
        tags: list[str] = []
        for item in raw:
            tag = str(item).strip().lstrip("#").strip()
            if not tag or len(tag) > 24:
                continue
            if tag not in tags:
                tags.append(tag)
        return tags[:12]

    @staticmethod
    def _normalize_links(value) -> list[str]:
        if value is None:
            return []
        raw = value if isinstance(value, (list, tuple)) else re.split(r"[,，;；]", str(value))
        links: list[str] = []
        for item in raw:
            link = str(item).strip()
            if link and link not in links:
                links.append(link)
        return links

    def _hashtags(self, text: str) -> list[str]:
        tags = []
        for match in HASHTAG_RE.finditer(text or ""):
            tag = match.group(1)
            if tag not in tags:
                tags.append(tag)
        return tags

    @staticmethod
    def _extract_links(body: str) -> list[str]:
        links: list[str] = []
        for match in WIKILINK_RE.finditer(body or ""):
            target = match.group(1).split("|")[0].split("#")[0].strip()
            if target and target not in links:
                links.append(target)
        return links

    def _unique_title(self, base: str) -> str:
        base = (base or "未命名").strip() or "未命名"
        if not self._exists(base):
            return base
        for index in range(2, 200):
            candidate = f"{base}（{index}）"
            if not self._exists(candidate):
                return candidate
        return f"{base}（{int(time.time())}）"

    def _path_for(self, discipline: str, title: str) -> Path:
        return self.vault / _safe_name(discipline) / f"{_safe_name(title)}.md"

    def _write_file(self, path: Path, meta: dict, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = fm.serialize(meta, body or "")
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)

    def close(self) -> None:
        with self._lock:
            self._db.close()
