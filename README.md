# RoboDocs

**A version-aware RAG assistant for robotics developers.** Paste an error or ask a question about
ROS 2, Nav2, MoveIt 2, ros2_control, Isaac Sim, Isaac Lab or MuJoCo, and get an answer grounded in the docs and
GitHub issues **for the version you actually use**, with links to the sources.

> 🚧 Work in progress. Built stage by stage as an end-to-end RAG learning project.
> **Stages 1–3 are complete** (collection, parsing & cleaning, chunking); Stage 4 (embeddings) is next.

## The problem

Robotics developers keep hitting errors that someone has already solved, but the fix is scattered
across official docs, GitHub issues, discussions, release notes and Q&A forums, and it is
**version-specific**. General LLMs make it worse by mixing versions and confidently giving outdated APIs.

Real example from the collected data: the error `No module named 'omni.isaac...'` appears in
**8 separate Isaac Lab issues**. One reporter explicitly tried the fix from an older issue, which
didn't apply to their Isaac Sim version, and had to open yet another issue.

RoboDocs retrieves only from the relevant framework and version, answers, cites the exact doc/issue,
and says "not found" when the sources don't cover the question.

## Pipeline

| Stage | What | Status |
|---|---|---|
| 1 | Data collection: git docs, docs website, GitHub GraphQL, Stack Exchange API, own notes | ✅ |
| 2 | Parsing & cleaning into one `Document` format with metadata (66,768 → 61,606 docs) | ✅ |
| 3 | Chunking: docs by heading, answers prefixed with their question, code intact (259,186 chunks; 0 cut code blocks vs 20.5% naive) | ✅ |
| 4 | Embeddings + vector store (local, open-source) | ⏳ |
| 5 | Retrieval: BM25 + vector hybrid, metadata filters, reranking | |
| 6 | Generation with citations and refusal (open-source LLM first) | |
| 7 | Evaluation on real held-out questions vs. a plain-LLM baseline | |
| 8 | FastAPI + chat UI | |
| 9 | Incremental refresh | |

## Stage 1: data collected

| Source | Items |
|---|---|
| Official docs from git (9 framework-versions + ros2_control) | 3,308 files |
| Isaac Sim docs website (5.1, 6.1) | 791 pages |
| GitHub closed issues (13 repos, with comments + "closed by PR" signal) | 12,885 |
| GitHub Discussions | 2,175 |
| Robotics Stack Exchange + Stack Overflow tags | 47,594 (84% with accepted answer) |
| **Total** | **~66,800 raw documents** |

How much of this is actually useful was measured with a **coverage audit** on real, recent developer
questions (only using content that existed before each question was asked). It found and fixed a source
gap (ros2_control). See [docs/records/](docs/records/) for the full write-ups, including what didn't work.

## Project layout

```
config/settings.yaml          all sources, versions and tunables
src/robodocs/collect/         one collector per source (resumable, rate-limit aware)
  docs.py                     sparse git clone of doc files per version tag/branch
  website.py                  Sphinx site → page list from searchindex.js
  github.py                   GraphQL issues + discussions, cursor checkpoints
  stackexchange.py            Q&A with answers via custom API filter, date-cursor paging
  notes.py                    own notes with secret/IP redaction
  pack.py                     many small JSON files → JSONL
  coverage_audit.py           FTS5/BM25 audit of corpus coverage
src/robodocs/process/          Stage 2: rst/html → Markdown, cleaning, version detection, parsers, dedup
src/robodocs/chunk/            Stage 3: content-aware chunker + naive baseline comparison
docs/PROJECT_SCOPE.md         requirements & scope
docs/records/                 per-stage records and audit results
tests/                        unit tests (pytest)
```

## Run it

```bash
conda create -n robodocs python=3.11 -y
conda activate robodocs
pip install -e ".[dev]"
cp .env.example .env          # add a free STACKEXCHANGE_KEY; GitHub uses `gh auth login`

python -m robodocs.collect.docs
python -m robodocs.collect.website
python -m robodocs.collect.github
python -m robodocs.collect.stackexchange
python -m robodocs.collect.pack
python -m robodocs.process.run    # Stage 2
python -m robodocs.chunk.run      # Stage 3
pytest -q
```

Collected data is **not** committed (`data/` is gitignored): it's regenerable, and the sources have
their own licenses. Every answer links back to the original source.

## Data sources & licenses

ROS 2 docs (CC-BY-4.0), Isaac Lab (BSD-3), MuJoCo (Apache-2.0), ros2_control (Apache-2.0), Isaac Sim (NVIDIA),
Stack Exchange content (CC BY-SA 4.0), GitHub issues/discussions (GitHub ToS). Personal, non-commercial
learning project; all content is attributed and linked to its source.
