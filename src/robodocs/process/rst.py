"""Lightweight reStructuredText -> Markdown for RAG (no pandoc/docutils needed).

Goal is NOT a perfect renderer. Goal: clean, readable text where
  - headings survive (Stage 3 chunks by heading),
  - code blocks survive intact and fenced,
  - tabs/notes/dropdowns keep their content,
  - `.. include::` is resolved from the downloaded repo (ROS 2 install steps live in includes),
  - Sphinx-only machinery (toctree, autodoc, redirects, meta) disappears,
  - content we could not fetch (literalinclude, mujoco-include) leaves a visible placeholder.
Directive list was built from a frequency survey of our actual corpus (Stage 2 notes).
"""

import re
import textwrap
from pathlib import Path

DIRECTIVE = re.compile(r"^(\s*)\.\.\s+([\w:.-]+)::\s?(.*)$")
COMMENT_OR_TARGET = re.compile(r"^(\s*)\.\.(\s|$)")
OPTION = re.compile(r"^\s*:[\w -]+:(\s.*)?$")
ADORNMENT = re.compile(r"^([=\-~^\"'`#*+<>_:.])\1{2,}\s*$")

CODE = {"code-block", "code", "sourcecode", "ipython", "prompt"}
ADMONITIONS = {"note", "warning", "tip", "important", "attention", "caution", "danger", "hint",
               "seealso", "error", "admonition", "deprecated", "versionadded", "versionchanged",
               "versionremoved", "todo"}
TITLED = {"tab", "group-tab", "tab-item", "code-tab", "dropdown", "card", "grid-item-card",
          "topic", "sidebar", "rubric"}
DROP = {"toctree", "contents", "meta", "redirect-from", "showmeta", "currentmodule", "module",
        "autosummary", "automodule", "autoclass", "autofunction", "automethod", "autoattribute",
        "autodata", "autoexception", "autoprogram", "raw", "index", "highlight",
        "sectionauthor", "spelling:word-list", "tags", "py:module", "py:currentmodule",
        "role", "default-role", "youtube", "video", "raw-html", "jinja"}
CODE_ROLES = {"class", "func", "meth", "attr", "mod", "obj", "data", "exc", "code", "file",
              "command", "program", "envvar", "at", "el", "commit", "samp", "kbd", "option",
              "const", "type", "member", "var", "macro", "struct", "enum"}

ROLE = re.compile(r":(?:[\w-]+:)*([\w-]+):`([^`]*)`")
LINK = re.compile(r"`([^`<]+?)\s*<([^>]+)>`__?")
NAMED_REF = re.compile(r"`([^`]+)`__?(?![\w])")
SUBSTITUTION = re.compile(r"\|([A-Za-z_]+)\|")
ESCAPED_SPACE = "\\" + " "          # RST "\ " (used to glue inline markup); spelled out to avoid escaping bugs
BACKSLASH_ESCAPE = re.compile(r"\\([_*`|\\])")                 # isaaclab\_ov -> isaaclab_ov
FILE_METADATA = re.compile(r"^:(github_url|orphan|tocdepth|nosearch|og:[\w:]+|description|keywords|html_theme\.[\w.]+):.*$",
                           re.M)                                     # Sphinx per-file fields, not content


def _inline(line: str) -> str:
    def role(m: re.Match) -> str:
        name, content = m.group(1), m.group(2)
        label = re.match(r"^(.*?)\s*<[^>]+>$", content, re.S)
        text = label.group(1) if label and label.group(1) else content
        text = text.lstrip("~!")
        if name == "math":
            return f"${text}$"
        if name == "icon":
            return ""
        return f"`{text}`" if name in CODE_ROLES else text

    line = ROLE.sub(role, line)
    line = LINK.sub(lambda m: f"[{m.group(1)}]({m.group(2)})" if "://" in m.group(2) else m.group(1), line)
    line = line.replace("``", "`").replace(ESCAPED_SPACE, "")
    line = SUBSTITUTION.sub(lambda m: m.group(1), line)
    line = BACKSLASH_ESCAPE.sub(lambda m: m.group(1), line)
    line = NAMED_REF.sub(lambda m: m.group(1), line)
    return line


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _take_block(lines: list[str], start: int, base_indent: int) -> tuple[list[str], int]:
    """Collect lines belonging to a directive: blank lines or lines indented deeper than base."""
    block, i = [], start
    while i < len(lines):
        ln = lines[i]
        if ln.strip() and _indent_of(ln) <= base_indent:
            break
        block.append(ln)
        i += 1
    while block and not block[-1].strip():
        block.pop()
    return block, i


def _split_options(block: list[str]) -> tuple[dict, list[str]]:
    opts, i = {}, 0
    while i < len(block) and block[i].strip() and OPTION.match(block[i]):
        k, _, v = block[i].strip()[1:].partition(":")
        opts[k.strip()] = v.strip()
        i += 1
    return opts, block[i:]


def _fence(body_lines: list[str], lang: str = "") -> list[str]:
    body = textwrap.dedent("\n".join(body_lines)).strip("\n")
    return [f"```{lang}".rstrip(), *body.splitlines(), "```"]


def rst_to_markdown(text: str, base_dir: Path | None = None, _depth: int = 0) -> str:
    """base_dir: folder of the .rst file, used to resolve `.. include::` (max depth 3)."""
    text = FILE_METADATA.sub("", text.lstrip("﻿"))
    lines = text.replace("\t", "    ").splitlines()
    out: list[str] = []
    heading_styles: list[tuple[str, bool]] = []

    def heading(title: str, char: str, over: bool) -> str:
        if (char, over) not in heading_styles:
            heading_styles.append((char, over))
        level = min(heading_styles.index((char, over)) + 1, 6)
        return "#" * level + " " + _inline(title.strip())

    def convert_body(body: list[str]) -> str:
        return rst_to_markdown(textwrap.dedent("\n".join(body)), base_dir, _depth).strip()

    i = 0
    while i < len(lines):
        ln = lines[i]

        # --- headings: overline + title + underline, or title + underline
        if ADORNMENT.match(ln) and i + 2 < len(lines) and lines[i + 1].strip() \
                and ADORNMENT.match(lines[i + 2]) and lines[i + 2].strip()[0] == ln.strip()[0]:
            out += ["", heading(lines[i + 1], ln.strip()[0], True), ""]
            i += 3
            continue
        if ln.strip() and not ln.startswith(" ") and i + 1 < len(lines) and ADORNMENT.match(lines[i + 1]) \
                and len(lines[i + 1].strip()) >= max(3, len(ln.strip()) - 2) and not ADORNMENT.match(ln):
            out += ["", heading(ln, lines[i + 1].strip()[0], False), ""]
            i += 2
            continue

        # --- directives
        m = DIRECTIVE.match(ln)
        if m:
            indent, name, arg = len(m.group(1)), m.group(2).lower(), m.group(3).strip()
            block, i = _take_block(lines, i + 1, indent)
            opts, body = _split_options(block)
            short = name.split(":")[-1]
            pad = " " * indent

            if short in CODE:
                out += [pad + l for l in _fence(body, arg.split()[0] if arg else opts.get("language", ""))]
            elif short == "include":
                inc = (base_dir / arg) if base_dir and arg and not arg.startswith("/") else None
                if inc and inc.is_file() and _depth < 3:
                    inner = rst_to_markdown(inc.read_text(encoding="utf-8", errors="replace"), inc.parent, _depth + 1)
                    out += [pad + l for l in inner.splitlines()]
            elif short == "literalinclude":
                out.append(f"{pad}[code included from `{arg}`]")
            elif short == "mujoco-include":
                out.append(f"{pad}[definition of `{arg}` included from MuJoCo headers]")
            elif short in {"image", "figure"}:
                alt = opts.get("alt", "")
                caption = " ".join(l.strip() for l in body if l.strip())[:200] if short == "figure" else ""
                desc = caption or alt or arg.rsplit("/", 1)[-1]
                out.append(f"{pad}[image: {_inline(desc)}]")
            elif short == "math":
                out += [pad + "$$", *[pad + l for l in textwrap.dedent("\n".join(body)).strip().splitlines()],
                        pad + "$$"]
            elif short in DROP or name in DROP:
                pass
            elif short in ADMONITIONS:
                label = arg if short == "admonition" and arg else short.capitalize()
                if short.startswith("version") or short == "deprecated":
                    label = f"{short.capitalize()} {arg}".strip()
                    arg = ""
                inner = convert_body(body)
                if short != "admonition" and arg:
                    inner = (_inline(arg) + "\n" + inner).strip()
                inner_lines = inner.splitlines() or [""]
                out += ["", f"{pad}> **{label}:** {inner_lines[0]}", *[f"{pad}> {l}" for l in inner_lines[1:]], ""]
            elif short in TITLED:
                inner = convert_body(body)
                out += ["", f"{pad}**{_inline(arg)}**" if arg else "", *[pad + l for l in inner.splitlines()], ""]
            else:  # unknown/transparent containers (tabs, tab-set, grid, list-table, only, ...): keep content
                if arg and short in {"list-table", "table", "csv-table"}:
                    out.append(f"{pad}**{_inline(arg)}**")
                out += [pad + l for l in convert_body(body).splitlines()]
            continue

        # --- comments and link targets (".. _label:", ".. some comment")
        if COMMENT_OR_TARGET.match(ln):
            _, i = _take_block(lines, i + 1, _indent_of(ln))
            continue

        # --- literal block introduced by "::"
        if ln.rstrip().endswith("::"):
            intro = ln.rstrip()[:-2].rstrip()
            if intro:
                out.append(_inline(intro) + ("" if intro.endswith(":") else ":"))
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and _indent_of(lines[j]) > _indent_of(ln):
                block, i = _take_block(lines, j, _indent_of(ln))
                out += _fence(block)
            else:
                i += 1
            continue

        out.append(_inline(ln))
        i += 1

    md = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
