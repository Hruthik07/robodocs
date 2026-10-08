"""Stage 1 (final step): pack the many small raw JSON files into a few JSONL files.

Why: 63k tiny files are slow to read on Windows (antivirus scans every file open).
One JSONL per source = one file open, read line by line. Same content, nothing changed.

    data/raw/github/<repo>/<kind>/*.json        -> data/raw/packed/github__<repo>__<kind>.jsonl
    data/raw/stackexchange/<source>/*.json      -> data/raw/packed/stackexchange__<source>.jsonl

The small files stay the source of truth (the collectors resume from them); re-run pack after
any new collection. Run:
    conda run -n robodocs python -m robodocs.collect.pack
"""

import json
from pathlib import Path

from tqdm import tqdm

from robodocs.config import get_settings


def item_files(folder: Path) -> list[Path]:
    """Numbered item files only (skip _state.json), sorted numerically for stable output."""
    return sorted((p for p in folder.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))


def pack_folder(folder: Path, out_file: Path) -> int:
    files = item_files(folder)
    tmp = out_file.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as out:
        for f in tqdm(files, desc=out_file.stem, unit="item", leave=False):
            obj = json.loads(f.read_text(encoding="utf-8"))
            out.write(json.dumps(obj, ensure_ascii=False) + "\n")
    tmp.replace(out_file)  # atomic: a crash never leaves a half-written .jsonl
    return len(files)


def main() -> None:
    settings = get_settings()
    raw = settings.abs_path(settings.paths.raw_data)
    packed = raw / "packed"
    packed.mkdir(exist_ok=True)

    jobs = [(d, packed / f"github__{d.parent.name}__{d.name}.jsonl")
            for d in sorted((raw / "github").glob("*/*")) if d.is_dir()]
    jobs += [(d, packed / f"stackexchange__{d.name}.jsonl")
             for d in sorted((raw / "stackexchange").glob("*")) if d.is_dir()]

    total = 0
    for folder, out_file in jobs:
        n = pack_folder(folder, out_file)
        total += n
        print(f"{out_file.name:58} {n:6} items  {out_file.stat().st_size / 1e6:7.1f} MB")
    print(f"\nTotal: {total} items in {len(jobs)} files")


if __name__ == "__main__":
    main()
