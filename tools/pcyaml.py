"""Paperclip's YAML subset: parser and emitter.

Paperclip parses package frontmatter and .paperclip.yaml with its own minimal
parser (server/src/services/company-portability.ts: prepareYamlLines,
parseYamlBlock, parseYamlScalar), not a full YAML library. Rules that follow:

  * 2-space indentation; children of `key:` must be exactly 2 deeper
  * list items sit 2 deeper than their key (`tags:\\n  - a`), never level with it
  * no block scalars (| or >), no anchors, no inline comments after values
  * multi-line {...}/[...] flow or JSON documents are not parsed
  * only `true`/`false` are booleans; quoted strings are read with JSON.parse

`parse` is a line-for-line port; `dump` emits only that subset (strings are
JSON-quoted, which both Paperclip and standard YAML read identically).
"""

from __future__ import annotations

import json
import re


def _scalar(raw: str):
    t = raw.strip()
    if t == "":
        return ""
    if t in ("null", "~"):
        return None
    if t == "true":
        return True
    if t == "false":
        return False
    if t == "[]":
        return []
    if t == "{}":
        return {}
    if re.fullmatch(r"-?\d+(\.\d+)?", t):
        return float(t) if "." in t else int(t)
    if t[0] in "\"[{":
        try:
            return json.loads(t)
        except ValueError:
            return t
    return t


def _lines(raw: str):
    out = []
    for line in raw.split("\n"):
        content = line.strip()
        if content and not content.startswith("#"):
            out.append((len(line) - len(line.lstrip(" ")), content))
    return out


def _block(lines, index: int, level: int):
    if index >= len(lines) or lines[index][0] < level:
        return {}, index
    if lines[index][0] == level and lines[index][1].startswith("-"):
        values = []
        while index < len(lines):
            indent, content = lines[index]
            if indent < level or indent != level or not content.startswith("-"):
                break
            rem = content[1:].strip()
            index += 1
            if not rem:
                nested, index = _block(lines, index, level + 2)
                values.append(nested)
                continue
            sep = rem.find(":")
            if sep > 0 and rem[0] not in "\"{[":
                obj = {rem[:sep].strip(): _scalar(rem[sep + 1:])}
                if index < len(lines) and lines[index][0] > level:
                    nested, index = _block(lines, index, level + 2)
                    if isinstance(nested, dict):
                        obj.update(nested)
                values.append(obj)
                continue
            values.append(_scalar(rem))
        return values, index
    record = {}
    while index < len(lines):
        indent, content = lines[index]
        if indent < level:
            break
        if indent != level:
            index += 1
            continue
        sep = content.find(":")
        if sep <= 0:
            index += 1
            continue
        key, rem = content[:sep].strip(), content[sep + 1:].strip()
        index += 1
        if not rem:
            nested, index = _block(lines, index, level + 2)
            record[key] = nested
            continue
        record[key] = _scalar(rem)
    return record, index


def parse(raw: str) -> dict:
    lines = _lines(raw)
    if not lines:
        return {}
    value, _ = _block(lines, 0, lines[0][0])
    return value if isinstance(value, dict) else {}


def _emit_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def _emit(value, indent: int) -> list[str]:
    pad = " " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(val, (dict, list)) and val:
                out.append(f"{pad}{key}:")
                out.extend(_emit(val, indent + 2))
            elif isinstance(val, dict):
                out.append(f"{pad}{key}: {{}}")
            elif isinstance(val, list):
                out.append(f"{pad}{key}: []")
            else:
                out.append(f"{pad}{key}: {_emit_scalar(val)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                out.append(f"{pad}-")
                out.extend(_emit(item, indent + 2))
            else:
                out.append(f"{pad}- {_emit_scalar(item)}")
    return out


def dump(value: dict) -> str:
    return "\n".join(_emit(value, 0)) + "\n"


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """(raw frontmatter or None, body) using Paperclip's delimiters."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 5:]
