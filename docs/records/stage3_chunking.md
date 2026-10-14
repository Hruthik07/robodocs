# Stage 3: Chunking (record)

**Date:** 2026-10-14 · **Status:** done · **Output:** `data/processed/chunks.jsonl` (+ `chunk_report.json`, `chunk_sample.md`)
**Run:** `python -m robodocs.chunk.run` (~30 s) · **Tests:** 66 passing

## Strategy (content-aware, `chunk/chunker.py`)
- **Docs / web docs / notes:** split at headings → merge sections < 250 chars into the next → pack paragraph
  blocks up to ~1,200 chars (hard max 1,800 incl. context). A fenced code block is one atomic block; only a
  single block > max is cut, on line breaks, and both halves are re-fenced.
  Context header: `ROS 2 jazzy docs | Ubuntu (deb packages) > System setup`.
- **Issues / discussions / Q&A:** question → up to 3 chunks; each accepted / maintainer answer is its own
  chunk; small replies are merged. **Every answer chunk is prefixed with the question title + first 300
  chars**, so a search for the problem finds the fix.
- Chunks keep the document's filter fields (framework, version, ros_generation, source_type, resolved) plus
  `is_accepted` / `by_maintainer`. Embedding input = `context + text`.

## Result: 61,606 documents → 259,186 chunks
Median 893 chars per chunk (with context), p95 1,737, max 1,804. Median 3 chunks per document.
Roles: section 42,724 · question 88,656 · answer 99,324 · reply 28,482.

## Compared with naive fixed-size chunking (1,200 chars, 200 overlap), same corpus

| | Content-aware | Naive |
|---|---|---|
| Code blocks cut in half | **0** | 48,340 (20.5%) |
| Answer chunks without their question | **0** | 55,540 of 88,936 (62%) |

## Issues found in the first run, fixed
| Found | Fix |
|---|---|
| 7.7% of chunks over the ~512-token embedding limit: the context header was not counted | size limit applies to context + text → 0.64% (borderline, real tokenizer in Stage 4) |
| 6,110 threads with > 3 question chunks (pasted logs) | cap at 3 question chunks (−13k chunks) |
| 1,310 chunks with an open code fence: users never closed ``` | close unbalanced fences per chunk → 0 |

## For Stage 4
- 259k chunks × ~250 tokens is a lot for CPU embedding: decide whether ROS 1 Q&A goes into the index.
- Verify the 3.5 chars/token estimate with the chosen model's real tokenizer.
- `maintainer` flag under-counts (e.g. core Isaac Lab developers show as CONTRIBUTOR).
