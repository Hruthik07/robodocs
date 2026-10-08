"""Stage 1e: coverage audit. Does our corpus contain the answers to real, recent problems?

Method
  1. Sample 50 recently closed, resolved GitHub issues (stratified by framework, fixed seed).
  2. For each, keyword-search (SQLite FTS5 / BM25) the rest of the corpus, using ONLY content
     that existed before the issue was opened: "could RoboDocs have answered this back then?"
  3. A human (or reviewer) judges each case from the printed evidence:
       covered | partial | gap (answer should exist, we lack it) | novel_bug (code fix, unanswerable)
     Coverage = (covered + 0.5*partial) / (all - novel_bug). Target: >= 80%.

Caveats (stated, not hidden)
  - Keyword search is weaker than the hybrid retrieval of Stage 5, so this UNDER-estimates
    what's findable; it never over-estimates.
  - Docs are today's snapshot, so a doc page might post-date an older issue (small leak).

Run:
    conda run -n robodocs python -m robodocs.collect.coverage_audit build     # index (~2 min)
    conda run -n robodocs python -m robodocs.collect.coverage_audit sample    # 50 cases + evidence
"""

import argparse
import json
import random
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from robodocs.config import get_settings
from robodocs.process.clean import fix_html_entities

MAX_BODY_CHARS = 20_000
SAMPLE_QUOTAS = {"isaac_lab": 12, "isaac_sim": 8, "mujoco": 10, "nav2": 10, "moveit2": 5, "ros2": 5}
RECENT_SINCE = "2026-04-07"          # ~6 months before collection
SKIP_LABELS = {"enhancement", "feature", "feature request", "proposal", "feature-request"}
MAINTAINER_ROLES = {"MEMBER", "OWNER", "COLLABORATOR"}
STOPWORDS = set("""a an the and or but if then else when while of to in on for with without from by
at as is are was were be been being it its this that these those i we you he she they my our your
not no can cannot can't could should would will just also only into out up down over under after
before about how what why where which who whom do does did done have has had get got using use used
error bug issue issues problem question help please work works working fails failed failing when
run running ran try tried trying""".split())


# ---------------------------------------------------------------------------
# Turning raw items into (title, body, created, url) for the index
# ---------------------------------------------------------------------------

def ts(iso: str | None) -> float | None:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def html_to_text(html: str) -> str:
    m = re.search(r"<article.*?</article>", html, re.S)
    html = m.group(0) if m else html
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", fix_html_entities(re.sub(r"<[^>]+>", " ", html)))


def iter_corpus(raw: Path):
    """Yield dicts: doc_id, source, framework, created (epoch|None), url, title, body."""
    for manifest in raw.glob("docs/*/*/manifest.json"):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        for f in m["files"]:
            p = manifest.parent / f["path"]
            yield {"doc_id": f"doc:{m['framework']}:{m['version']}:{f['path']}", "source": "docs",
                   "framework": m["framework"], "created": None, "url": f["url"],
                   "title": f["path"], "body": p.read_text(encoding="utf-8", errors="replace")}
    for manifest in raw.glob("web/*/*/manifest.json"):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        for f in m["files"]:
            p = manifest.parent / f["path"]
            yield {"doc_id": f"web:{m['framework']}:{m['version']}:{f['path']}", "source": "web",
                   "framework": m["framework"], "created": None, "url": f["url"], "title": f["path"],
                   "body": html_to_text(p.read_text(encoding="utf-8", errors="replace"))}
    for packed in raw.glob("packed/github__*.jsonl"):
        for line in open(packed, encoding="utf-8"):
            it = json.loads(line)
            parts = [it.get("body") or ""] + [c.get("body") or "" for c in it["comments"]["nodes"]]
            if it.get("answer"):
                parts.append(it["answer"].get("body") or "")
            for c in it["comments"]["nodes"]:
                parts += [r.get("body") or "" for r in (c.get("replies") or {}).get("nodes", [])]
            yield {"doc_id": f"gh:{it['url']}", "source": it["_meta"]["source"],
                   "framework": it["_meta"]["framework"], "created": ts(it["createdAt"]),
                   "url": it["url"], "title": it["title"], "body": "\n".join(parts)}
    for packed in raw.glob("packed/stackexchange__*.jsonl"):
        for line in open(packed, encoding="utf-8"):
            q = json.loads(line)
            parts = [q.get("body_markdown", "")] + [a.get("body_markdown", "") for a in q.get("answers", [])]
            yield {"doc_id": f"se:{q['link']}", "source": "stackexchange", "framework": "",
                   "created": float(q["creation_date"]), "url": q["link"],
                   "title": fix_html_entities(q["title"]), "body": fix_html_entities("\n".join(parts))}
    for f in (raw / "notes").rglob("*.md"):
        yield {"doc_id": f"note:{f.relative_to(raw / 'notes').as_posix()}", "source": "notes",
               "framework": "", "created": None, "url": str(f), "title": f.name,
               "body": f.read_text(encoding="utf-8", errors="replace")}


def build_index(raw: Path, db_path: Path) -> int:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("CREATE VIRTUAL TABLE t USING fts5(doc_id UNINDEXED, source UNINDEXED, "
                "framework UNINDEXED, created UNINDEXED, url UNINDEXED, title, body)")
    n = 0
    batch = []
    for d in iter_corpus(raw):
        batch.append((d["doc_id"], d["source"], d["framework"], d["created"], d["url"],
                      d["title"], d["body"][:MAX_BODY_CHARS]))
        n += 1
        if len(batch) >= 2000:
            con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?)", batch)
            batch.clear()
    con.executemany("INSERT INTO t VALUES (?,?,?,?,?,?,?)", batch)
    con.commit()
    con.close()
    return n


# ---------------------------------------------------------------------------
# Sampling + evidence
# ---------------------------------------------------------------------------

def query_terms(title: str, body: str, limit: int = 18) -> list[str]:
    """Title words + words from error-looking lines (where the searchable signal is)."""
    err_lines = [l for l in (body or "").splitlines()
                 if re.search(r"(?i)error|exception|traceback|failed|not found|cannot|undefined|warn", l)][:4]
    terms = []
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", title + " " + " ".join(err_lines)):
        tok = tok.strip(".").lower()
        if tok not in STOPWORDS and tok not in terms and len(tok) > 2:
            terms.append(tok)
    return terms[:limit]


def resolution_text(issue: dict) -> str:
    comments = issue["comments"]["nodes"]
    maint = [c for c in comments if c["authorAssociation"] in MAINTAINER_ROLES]
    chosen = (maint or comments)[-1:]
    closer = (issue["timelineItems"]["nodes"] or [{}])[0].get("closer") or {}
    pr = f"[closed by PR: {closer.get('title')}] " if closer.get("__typename") == "PullRequest" else ""
    return pr + " ".join((c.get("body") or "")[:600] for c in chosen)


def sample_issues(raw: Path, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    pools: dict[str, list] = {fw: [] for fw in SAMPLE_QUOTAS}
    for packed in raw.glob("packed/github__*__issues.jsonl"):
        for line in open(packed, encoding="utf-8"):
            it = json.loads(line)
            fw = it["_meta"]["framework"]
            labels = {l["name"].lower() for l in it["labels"]["nodes"]}
            if (fw in pools and it["closedAt"] >= RECENT_SINCE and it["stateReason"] == "COMPLETED"
                    and it["comments"]["totalCount"] >= 2 and not labels & SKIP_LABELS
                    and not re.match(r"(?i)\[(feature|proposal|enhancement)", it["title"])):
                pools[fw].append(it)
    picked = []
    for fw, k in SAMPLE_QUOTAS.items():
        picked += rng.sample(pools[fw], min(k, len(pools[fw])))
    return picked


# --- v2: sample real QUESTIONS with a confirmed answer (v1 sampled issues; 76% weren't questions)

QUESTION_QUOTAS = {"isaac_lab": 10, "isaac_sim": 8, "mujoco": 10, "ros2": 12, "nav2": 6, "moveit2": 4}
QUESTIONS_SINCE = "2025-10-01"   # recent: last ~12 months


def _q(fw, url, doc_id, created_iso, title, body, resolution, kind):
    return {"framework": fw, "url": url, "doc_id": doc_id, "created": created_iso, "title": title,
            "body": body or "", "resolution": resolution or "", "kind": kind}


def sample_questions(raw: Path, seed: int = 42) -> list[dict]:
    from robodocs.process.clean import ros_generation
    pools: dict[str, list] = {fw: [] for fw in QUESTION_QUOTAS}

    # (a) answered GitHub Discussions: the asker marked an answer
    for packed in raw.glob("packed/github__*__discussions.jsonl"):
        for line in open(packed, encoding="utf-8"):
            d = json.loads(line)
            fw = d["_meta"]["framework"]
            if fw in pools and d.get("answer") and d["createdAt"] >= QUESTIONS_SINCE:
                pools[fw].append(_q(fw, d["url"], f"gh:{d['url']}", d["createdAt"], d["title"],
                                    d["body"], d["answer"]["body"], "discussion"))
    # (b) GitHub issues that are questions, answered by a maintainer
    for packed in raw.glob("packed/github__*__issues.jsonl"):
        for line in open(packed, encoding="utf-8"):
            it = json.loads(line)
            fw = it["_meta"]["framework"]
            labels = {l["name"].lower() for l in it["labels"]["nodes"]}
            is_question = any("question" in l for l in labels) or it["title"].lower().startswith("[question]")
            maint = [c for c in it["comments"]["nodes"] if c["authorAssociation"] in MAINTAINER_ROLES]
            if fw in pools and is_question and maint and it["createdAt"] >= QUESTIONS_SINCE:
                pools[fw].append(_q(fw, it["url"], f"gh:{it['url']}", it["createdAt"], it["title"],
                                    it["body"], maint[-1]["body"], "question_issue"))
    # (c) Stack Exchange with an ACCEPTED answer, ROS 2 era only
    for packed in raw.glob("packed/stackexchange__*.jsonl"):
        for line in open(packed, encoding="utf-8"):
            q = json.loads(line)
            created = datetime.fromtimestamp(q["creation_date"], timezone.utc).isoformat()
            acc = [a for a in q.get("answers", []) if a.get("is_accepted")]
            if not acc or created < QUESTIONS_SINCE:
                continue
            tags = set(q["tags"])
            fw = ("moveit2" if tags & {"moveit", "moveit2"} else "nav2" if tags & {"nav2", "navigation2"}
                  else "mujoco" if "mujoco" in tags
                  else "ros2" if ros_generation(q["tags"], q["creation_date"]) == "ros2" else None)
            if fw in pools:
                pools[fw].append(_q(fw, q["link"], f"se:{q['link']}", created,
                                    fix_html_entities(q["title"]), fix_html_entities(q["body_markdown"]),
                                    fix_html_entities(acc[0]["body_markdown"]), "stackexchange"))

    rng = random.Random(seed)
    picked = []
    for fw, k in QUESTION_QUOTAS.items():
        print(f"  pool {fw:10} {len(pools[fw]):5} candidate questions -> taking {min(k, len(pools[fw]))}")
        picked += rng.sample(pools[fw], min(k, len(pools[fw])))
    return picked


def search_before(con: sqlite3.Connection, terms: list[str], before: float, exclude: str, k: int = 5):
    if not terms:
        return []
    q = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
    sql = ("SELECT source, framework, url, title, snippet(t, 6, '[', ']', ' … ', 28) "
           "FROM t WHERE t MATCH ? AND (created IS NULL OR created < ?) AND doc_id != ? "
           "ORDER BY bm25(t, 0, 0, 0, 0, 0, 3.0, 1.0) LIMIT ?")
    return con.execute(sql, (q, before, exclude, k)).fetchall()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["build", "sample", "sample-questions"])
    args = parser.parse_args()
    s = get_settings()
    raw = s.abs_path(s.paths.raw_data)
    db = s.abs_path(Path("data/index/audit_fts.sqlite"))

    if args.cmd == "build":
        print(f"indexed {build_index(raw, db)} documents -> {db}")
        return

    con = sqlite3.connect(db)
    if args.cmd == "sample-questions":
        cases = []
        for i, q in enumerate(sample_questions(raw), 1):
            terms = query_terms(q["title"], q["body"])
            hits = search_before(con, terms, ts(q["created"]), q["doc_id"])
            cases.append({"n": i, "framework": q["framework"], "kind": q["kind"], "url": q["url"],
                          "created": q["created"][:10], "title": q["title"],
                          "problem": re.sub(r"\s+", " ", q["body"])[:400],
                          "resolution": re.sub(r"\s+", " ", q["resolution"])[:500], "terms": terms,
                          "hits": [{"source": h[0], "url": h[2], "title": h[3],
                                    "snippet": re.sub(r"\s+", " ", h[4])} for h in hits]})
        out = db.parent / "audit_v2_cases.jsonl"
        out.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
        print(f"{len(cases)} cases -> {out}")
        return

    cases = []
    for i, it in enumerate(sample_issues(raw), 1):
        terms = query_terms(it["title"], it.get("body") or "")
        hits = search_before(con, terms, ts(it["createdAt"]), f"gh:{it['url']}")
        case = {"n": i, "framework": it["_meta"]["framework"], "url": it["url"],
                "created": it["createdAt"][:10], "title": it["title"],
                "problem": re.sub(r"\s+", " ", (it.get("body") or ""))[:400],
                "resolution": re.sub(r"\s+", " ", resolution_text(it))[:500],
                "terms": terms,
                "hits": [{"source": h[0], "url": h[2], "title": h[3], "snippet": re.sub(r"\s+", " ", h[4])}
                         for h in hits]}
        cases.append(case)
    out = db.parent / "audit_cases.jsonl"
    out.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases), encoding="utf-8")
    print(f"{len(cases)} cases -> {out}")


if __name__ == "__main__":
    main()
