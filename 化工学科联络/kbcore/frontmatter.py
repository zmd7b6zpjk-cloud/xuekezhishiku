"""极简 YAML frontmatter 读写。

只支持知识库自己会写出的子集：标量、引号字符串、行内列表 ``[a, b]``
以及块状列表。未知的键会原样保留，方便用户用 Obsidian 等工具扩展。
"""

from __future__ import annotations

import re

_FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n?", re.S | re.M)
_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$")
_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}


def parse(text: str) -> tuple[dict, str]:
    """返回 (meta, body)。没有 frontmatter 时 meta 为空。"""
    match = _FM_RE.match(text or "")
    if not match:
        return {}, text or ""
    return _parse_block(match.group(1)), text[match.end():]


def _parse_block(raw: str) -> dict:
    meta: dict = {}
    key: str | None = None
    items: list | None = None

    def flush() -> None:
        nonlocal key, items
        if key is not None and items is not None:
            meta[key] = items
        key, items = None, None

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and items is not None:
            items.append(_coerce(_unquote(stripped[2:].strip())))
            continue
        match = _KEY_RE.match(stripped)
        if not match:
            continue
        flush()
        name, value = match.group(1), match.group(2).strip()
        if value == "":
            key, items = name, []
            meta[name] = []
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[name] = [_coerce(_unquote(part.strip())) for part in _split_list(inner)] if inner else []
        else:
            meta[name] = _coerce(_unquote(value))
    flush()
    return meta


def _split_list(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for char in text:
        if quote:
            buf.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return parts


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return value


def _coerce(value):
    if not isinstance(value, str):
        return value
    low = value.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    if re.fullmatch(r"-?\d{1,9}", value):
        return int(value)
    return value


_ORDER = ("title", "discipline", "tags", "created", "updated")


def _needs_quotes(value: str) -> bool:
    if value == "" or value != value.strip():
        return True
    if value.lower() in _TRUE | _FALSE | {"null", "~"}:
        return True
    if re.fullmatch(r"-?\d+(\.\d+)?", value):
        return True
    if re.search(r"[:#\[\]{},&*!|>%@`\"']", value):
        return True
    return value[0] in "-? " or value[-1] == ":"


def _fmt_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = "" if value is None else str(value)
    if _needs_quotes(text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def serialize(meta: dict, body: str) -> str:
    lines = ["---"]
    keys = [key for key in _ORDER if key in meta]
    keys += sorted(key for key in meta if key not in _ORDER)
    for key in keys:
        value = meta[key]
        if isinstance(value, (list, tuple)):
            if not value:
                continue
            lines.append(f"{key}: [{', '.join(_fmt_scalar(item) for item in value)}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        else:
            if value is None or str(value) == "":
                continue
            lines.append(f"{key}: {_fmt_scalar(value)}")
    lines.append("---")
    text = "\n".join(lines)
    return text + "\n\n" + (body or "").strip("\n") + "\n"
