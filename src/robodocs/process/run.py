"""Stage 2 runner: raw data -> data/processed/documents.jsonl (+ report.json, sample.md).

    conda run -n robodocs python -m robodocs.process.run

Steps: parse every source -> drop with a recorded reason -> deduplicate -> write.
Dedup rules:
  - same doc_id twice (e.g. a Stack Overflow question tagged both ros2 and moveit) -> keep one
  - identical text (content_hash) -> keep one
  - same question in two places (Isaac Lab moves issues to Discussions) -> keep the copy with the
    best answer signals. Identical doc pages across *versions* are NOT duplicates: each is correct
    for its own version.
"""

import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from tqdm import tqdm

from robodocs.config import get_settings
from robodocs.process.parsers import (iter_packed, parse_discussion, parse_git_docs, parse_issue,
                                      parse_notes, parse_se, parse_web_docs)
from robodocs.process.schema import Document


def question_key(doc: Document) -> str | None:
    """Fingerprint of 'the same question': normalized title + start of the question body."""
    if doc.source_type not in {"issue", "discussion", "qa"}:
        return None
    m = re.search(r"## Question[^\n]*\n+(.{0,300})", doc.text, re.S)
    norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
    return f"{doc.framework}|{norm(doc.title)}|{norm(m.group(1) if m else '')}"


def quality(doc: Document) -> tuple:
    return (bool(doc.has_accepted_answer), bool(doc.resolved), bool(doc.maintainer_answered), len(doc.text))


def main() -> None:
    s = get_settings()
    raw = s.abs_path(s.paths.raw_data)
    out_dir = s.abs_path(s.paths.processed_data)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = s.processing

    stats: dict[str, Counter] = defaultdict(Counter)
    kept: dict[str, Document] = {}

    def consume(source: str, results):
        for doc, reason in tqdm(results, desc=source, unit="doc", leave=False):
            stats[source]["raw"] += 1
            if doc is None:
                stats[source][f"drop:{reason}"] += 1
            elif doc.doc_id in kept:
                stats[source]["drop:duplicate_id"] += 1
            else:
                kept[doc.doc_id] = doc

    consume("git_docs", parse_git_docs(raw, cfg))
    consume("web_docs", parse_web_docs(raw, cfg))
    consume("notes", parse_notes(raw, cfg))
    consume("github_issues", (parse_issue(x, cfg) for x in iter_packed(raw, "github__*__issues.jsonl")))
    consume("github_discussions", (parse_discussion(x, cfg) for x in iter_packed(raw, "github__*__discussions.jsonl")))
    consume("stackexchange", (parse_se(x, cfg) for x in iter_packed(raw, "stackexchange__*.jsonl")))

    source_of = {"doc": "git_docs", "web_doc": "web_docs", "note": "notes", "issue": "github_issues",
                 "discussion": "github_discussions", "qa": "stackexchange"}

    # --- exact duplicates (same text) ---------------------------------------------------------
    by_hash: dict[str, str] = {}
    for doc_id, doc in list(kept.items()):
        if doc.source_type in {"doc", "web_doc"}:      # same page in two versions is legitimate
            continue
        if doc.content_hash in by_hash:
            stats[source_of[doc.source_type]]["drop:exact_duplicate"] += 1
            del kept[doc_id]
        else:
            by_hash[doc.content_hash] = doc_id

    # --- near duplicates (same question asked/moved twice) -----------------------------------
    groups: dict[str, list[str]] = defaultdict(list)
    for doc_id, doc in kept.items():
        k = question_key(doc)
        if k:
            groups[k].append(doc_id)
    for ids in groups.values():
        if len(ids) > 1:
            best = max(ids, key=lambda i: quality(kept[i]))
            for i in ids:
                if i != best:
                    stats[source_of[kept[i].source_type]]["drop:same_question_elsewhere"] += 1
                    del kept[i]

    for doc in kept.values():
        stats[source_of[doc.source_type]]["kept"] += 1

    # --- write ----------------------------------------------------------------------------------
    docs = sorted(kept.values(), key=lambda d: d.doc_id)
    with open(out_dir / "documents.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            f.write(d.model_dump_json() + "\n")

    report = {
        "total_raw": sum(c["raw"] for c in stats.values()),
        "total_kept": len(docs),
        "by_source": {k: dict(v) for k, v in stats.items()},
        "kept_by_framework": dict(Counter(d.framework for d in docs).most_common()),
        "kept_by_type": dict(Counter(d.source_type for d in docs).most_common()),
        "version_known": {t: f"{sum(d.version != 'unknown' for d in docs if d.source_type == t)}"
                             f"/{sum(1 for d in docs if d.source_type == t)}"
                          for t in ["issue", "discussion", "qa"]},
        "ros_generation": dict(Counter(d.ros_generation for d in docs if d.source_type == "qa")),
        "text_chars": {"total": sum(len(d.text) for d in docs),
                       "median": sorted(len(d.text) for d in docs)[len(docs) // 2] if docs else 0},
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # --- random sample for the manual check (Stage 2, step 7) ----------------------------------
    rng = random.Random(7)
    sample = rng.sample(docs, min(20, len(docs)))
    md = ["# Stage 2 manual-check sample (seed 7)\n"]
    for d in sample:
        md += [f"## {d.title[:100]}", f"`{d.doc_id}` · {d.source_type} · {d.framework} · v={d.version} · "
               f"gen={d.ros_generation} · resolved={d.resolved} · {len(d.text)} chars · {d.url}", "",
               "```text", d.text[:900], "```", ""]
    (out_dir / "sample.md").write_text("\n".join(md), encoding="utf-8")

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
