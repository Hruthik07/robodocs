"""Stage 1d: collect the owner's own project notes (source D10), with secrets redacted.

    data/raw/notes/<folder>/<path>.md   (redacted copy)
    data/raw/notes/manifest.json        (what was copied, how many redactions per file)

Run: conda run -n robodocs python -m robodocs.collect.notes

Always re-copies everything (it's ~20 small files), so edits to your notes are picked up.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from robodocs.config import get_settings

# Patterns for things that must never reach an external LLM API.
SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws_secret", re.compile(r"(?i)(aws_secret_access_key\s*[=:]\s*)\S+")),
    ("github_token", re.compile(r"\b(ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("api_key", re.compile(r"\b(sk|rl|gsk|pk)-?_?[A-Za-z0-9]{20,}\b")),
    ("generic_secret", re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\s*[=:]\s*['\"]?[^\s'\"]{8,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Replace secrets with [REDACTED:<kind>]. Returns (clean text, counts per kind)."""
    counts = {}
    for kind, pattern in SECRET_PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        if n:
            counts[kind] = n
    return text, counts


def find_notes(root: Path, folders: list[str], include: list[str],
               exclude_names: list[str], exclude_dirs: list[str]) -> list[Path]:
    found = []
    for folder in folders:
        for pattern in include:
            for p in (root / folder).glob(pattern):
                rel_parts = p.relative_to(root).parts
                if p.is_file() and p.name not in exclude_names and not set(rel_parts) & set(exclude_dirs):
                    found.append(p)
    return sorted(set(found))


def main() -> None:
    settings = get_settings()
    cfg = settings.collection.notes
    out = settings.abs_path(settings.paths.raw_data) / "notes"
    if out.exists():
        shutil.rmtree(out)

    files, total_redactions = [], 0
    for src in find_notes(cfg.root, cfg.folders, cfg.include, cfg.exclude_names, cfg.exclude_dirs):
        rel = src.relative_to(cfg.root)
        text, counts = redact(src.read_text(encoding="utf-8", errors="replace"))
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        total_redactions += sum(counts.values())
        files.append({"path": rel.as_posix(), "source_path": str(src), "bytes": len(text.encode()),
                      "modified_at": datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                      "redactions": counts})

    manifest = {"source": "notes", "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "file_count": len(files), "total_redactions": total_redactions, "files": files}
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    for f in files:
        flag = f"  redacted: {f['redactions']}" if f["redactions"] else ""
        print(f"{f['path']:60} {f['bytes']:7} B{flag}")
    print(f"\nTotal: {len(files)} files, {total_redactions} redactions")


if __name__ == "__main__":
    main()
