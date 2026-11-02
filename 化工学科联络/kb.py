#!/usr/bin/env python3
"""化工学科联络 · 本地知识库

用法：
    python kb.py                # 启动本地界面（同 serve）
    python kb.py serve --lan    # 手机 / 局域网访问
    python kb.py add "标题" -d 化学工程 -t 热力学,相平衡 -b "正文"
    python kb.py search 逸度
    python kb.py ingest         # 导入 inbox/ 里的文件
    python kb.py doctor         # 检查断链、孤立卡片
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from kbcore import __version__  # noqa: E402
from kbcore import server as kbserver  # noqa: E402
from kbcore.store import KBError, Store  # noqa: E402

_EPILOG = """示例:
  python kb.py add "催化剂表征" -d 材料 -t 催化,BET -b "BET 方程见 [[催化剂与多孔材料：BET 与孔结构]]"
  python kb.py search "相平衡"
  python kb.py ingest
  python kb.py backup
"""


def _prepare_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _root() -> Path:
    return Path(os.environ.get("KB_ROOT") or ROOT).expanduser().resolve()


def _store() -> Store:
    return Store(_root())


def _read_body(args) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8-sig")
    body = args.body or ""
    if not body and not sys.stdin.isatty():
        body = sys.stdin.read()
    return body


def cmd_add(args) -> int:
    store = _store()
    try:
        entry = store.create(
            title=args.title,
            body=_read_body(args),
            discipline=args.discipline,
            tags=args.tags,
        )
    finally:
        store.close()
    print(f"已存入：{entry['title']}  [{entry['discipline']}]  {entry['path']}")
    print(f"标签：{'、'.join(entry['tags']) or '无'}    字数：{entry['words']}")
    return 0


def cmd_search(args) -> int:
    store = _store()
    try:
        result = store.query(q=" ".join(args.words), limit=args.limit)
    finally:
        store.close()
    if not result["items"]:
        print("没有找到匹配的卡片。")
        return 0
    print(f"找到 {result['total']} 条：\n")
    for item in result["items"]:
        print(f"[{item['discipline']}] {item['title']}")
        if item["excerpt"]:
            print(f"    {item['excerpt']}")
        print(f"    标签：{'、'.join(item['tags']) or '无'}    更新：{item['updated']}")
    return 0


def cmd_list(args) -> int:
    store = _store()
    try:
        items = store.query(limit=5000)["items"]
    finally:
        store.close()
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["discipline"], []).append(item)
    for discipline in sorted(groups):
        print(f"\n【{discipline}】({len(groups[discipline])})")
        for item in groups[discipline]:
            print(f"  · {item['title']}")
    print(f"\n共 {len(items)} 张卡片。")
    return 0


def cmd_show(args) -> int:
    store = _store()
    try:
        entry = store.get(args.title)
    finally:
        store.close()
    print(f"# {entry['title']}")
    print(f"学科：{entry['discipline']}    标签：{'、'.join(entry['tags']) or '无'}")
    print(f"创建：{entry['created']}    更新：{entry['updated']}    字数：{entry['words']}")
    print(f"路径：{entry['path']}")
    print("-" * 60)
    print(entry["body"])
    if entry["links_resolved"]:
        print("\n指向：" + "、".join(entry["links_resolved"]))
    if entry["backlinks"]:
        print("被引用：" + "、".join(entry["backlinks"]))
    if entry["dangling"]:
        print("待创建：" + "、".join(entry["dangling"]))
    return 0


def cmd_ingest(args) -> int:
    store = _store()
    try:
        result = store.ingest_inbox()
    finally:
        store.close()
    for item in result["added"]:
        print(f"已导入：{item['title']}  <- inbox/{item['source']}")
    for item in result["errors"]:
        print(f"失败：{item['file']}：{item['error']}", file=sys.stderr)
    print(f"完成：导入 {len(result['added'])} 个，失败 {len(result['errors'])} 个，剩余 {result['remaining']} 个。")
    return 0 if not result["errors"] else 1


def cmd_import(args) -> int:
    root = _root()
    inbox = root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    copied = 0
    for source in args.paths:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            print(f"跳过（不是文件）：{path}", file=sys.stderr)
            continue
        if path.suffix.lower() not in (".md", ".txt"):
            print(f"跳过（只支持 .md / .txt）：{path.name}", file=sys.stderr)
            continue
        destination = inbox / path.name
        if destination.exists():
            destination = inbox / f"{path.stem}-{secrets.token_hex(2)}{path.suffix}"
        shutil.copy2(path, destination)
        copied += 1
    print(f"已复制 {copied} 个文件到 inbox/，正在导入…")
    return cmd_ingest(args)


def cmd_reindex(args) -> int:
    store = _store()
    try:
        changed = store.sync(force=True)
        stats = store.stats()
    finally:
        store.close()
    print(f"索引已刷新：处理 {changed} 个变化文件，共 {stats['cards']} 张卡片。")
    return 0


def cmd_stats(args) -> int:
    store = _store()
    try:
        stats = store.stats()
    finally:
        store.close()
    print(f"卡片：{stats['cards']} 张    总字数：{stats['words']}    双链：{stats['links']} 条")
    print(f"收件箱：{stats['inbox']} 个待导入文件")
    print(f"数据目录：{stats['root']}")
    print("\n学科分布：")
    for item in stats["disciplines"]:
        print(f"  {item['name']:<10} {item['count']:>3} 张")
    if stats["tags"]:
        print("\n高频标签：" + "、".join(f"#{tag['name']}({tag['count']})" for tag in stats["tags"][:12]))
    return 0


def cmd_doctor(args) -> int:
    store = _store()
    try:
        report = store.doctor()
    finally:
        store.close()
    print(f"检查了 {report['cards']} 张卡片。")
    if report["dangling"]:
        print("\n断链（指向不存在的卡片）：")
        for item in report["dangling"]:
            print(f"  {item['from']} -> [[{item['to']}]]")
    if report["orphans"]:
        print("\n孤立卡片（没有任何联系）：")
        for title in report["orphans"]:
            print(f"  {title}")
    if report["untagged"]:
        print("\n没有标签的卡片：")
        for title in report["untagged"]:
            print(f"  {title}")
    if report["empty"]:
        print("\n正文为空的卡片：")
        for title in report["empty"]:
            print(f"  {title}")
    print("\n一切正常。" if report["ok"] else "\n以上问题不影响使用，可按需补充。")
    return 0


def cmd_backup(args) -> int:
    store = _store()
    try:
        destination = store.backup()
    finally:
        store.close()
    print(f"备份完成：{destination}")
    return 0


def cmd_serve(args) -> int:
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    token = args.token or ""
    if args.lan and not token:
        token = secrets.token_urlsafe(6)
    store = Store(_root())
    try:
        kbserver.run_server(
            store,
            host=host,
            port=args.port,
            token=token,
            open_browser=not args.no_open,
        )
    finally:
        store.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kb.py",
        description="化工学科联络 · 本地知识库（纯本地、无需联网）",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="启动本地网页界面")
    serve.add_argument("--port", type=int, default=8765, help="端口，默认 8765")
    serve.add_argument("--host", default=None, help="监听地址，默认 127.0.0.1")
    serve.add_argument("--lan", action="store_true", help="允许局域网 / 手机访问（自动生成令牌）")
    serve.add_argument("--token", default="", help="自定义访问令牌")
    serve.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    serve.set_defaults(func=cmd_serve)

    add = sub.add_parser("add", help="用命令行存入一张卡片")
    add.add_argument("title")
    add.add_argument("-b", "--body", default="")
    add.add_argument("-f", "--file", type=Path, help="从文件读取正文")
    add.add_argument("-d", "--discipline", default="", help="学科，默认未分类")
    add.add_argument("-t", "--tags", default="", help="标签，逗号分隔")
    add.set_defaults(func=cmd_add)

    search = sub.add_parser("search", help="搜索卡片")
    search.add_argument("words", nargs="+")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)

    listing = sub.add_parser("list", help="按学科列出全部卡片")
    listing.set_defaults(func=cmd_list)

    show = sub.add_parser("show", help="查看一张卡片的正文")
    show.add_argument("title")
    show.set_defaults(func=cmd_show)

    ingest = sub.add_parser("ingest", help="导入 inbox/ 中的 .md / .txt")
    ingest.set_defaults(func=cmd_ingest)

    imp = sub.add_parser("import", help="把外部文件复制进收件箱并导入")
    imp.add_argument("paths", nargs="+")
    imp.set_defaults(func=cmd_import)

    reindex = sub.add_parser("reindex", help="重建索引")
    reindex.set_defaults(func=cmd_reindex)

    stats = sub.add_parser("stats", help="统计信息")
    stats.set_defaults(func=cmd_stats)

    doctor = sub.add_parser("doctor", help="检查断链 / 孤立卡片")
    doctor.set_defaults(func=cmd_doctor)

    backup = sub.add_parser("backup", help="打包备份到 backups/")
    backup.set_defaults(func=cmd_backup)

    return parser


def main(argv=None) -> int:
    _prepare_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["serve"]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 1
    try:
        return args.func(args) or 0
    except KBError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
