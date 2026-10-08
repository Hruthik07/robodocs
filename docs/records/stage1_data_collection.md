# Stage 1: Data collection (record)

**Date:** 2026-10-07 · **Status:** collection done; 1d (own notes) and 1e (coverage audit) pending

## What was collected

| Source | Module | Items | Notes |
|---|---|---|---|
| D1–D4, D6 official docs (git) | `collect/docs.py` | 2,951 files, 9 framework-versions | sparse clone, commit SHA in each manifest |
| D5 Isaac Sim docs website | `collect/website.py` | 791 pages (5.1: 310, 6.1: 481), 0 missing | page list from Sphinx `searchindex.js`; raw HTML |
| D7 GitHub closed issues | `collect/github.py` | 10,829 (10 repos) | GraphQL, comments + "closed by PR" signal |
| D8 GitHub discussions | `collect/github.py` | 2,175 | incl. marked answer |
| D9 Stack Exchange | `collect/stackexchange.py` | 47,594 (Robotics SE 46,955 + SO 639) | 84% have an accepted answer |
| Packed raw | `collect/pack.py` | 60,598 items → 20 JSONL files | read time: minutes → 2.7 s |

All counts match the totals reported by the source APIs.

## Problems found and fixed

| # | Problem | Fix |
|---|---|---|
| 1 | Isaac Sim git repo has changelogs/API refs but **no tutorials** | Website collector (D5), incl. ROS 2 tutorials + migration guides |
| 2 | ~26k SE questions are ROS 1 | `process/clean.py::ros_generation` → ros1 26,470 · ros2 5,085 · both 109 · unknown 15,930 (14,039 of which are non-ROS robotics) |
| 3 | HTML entities in SE bodies (37,674 posts) | `fix_html_entities`, unescape up to twice (0.2% double-escaped at source) → 0 left |
| 4 | 63k small files slow on Windows | JSONL packing |

## Learned
- Check what a source *actually contains* before trusting it (Isaac Sim repo ≠ Isaac Sim docs).
- Robotics SE is ROS-1-heavy and has ~no Isaac/MuJoCo content; GitHub is the Q&A source there.
- Verify cleaning rules on real data, not just unit tests: both the date-rule bug and the
  double-escaping were found that way.

## 1d: own notes
`collect/notes.py`: 15 `.md` files from ISSAC / pybullet / embodied-ai-project (`CLAUDE.md` excluded),
secrets + IPs redacted before saving (5 redactions in ISSAC/RESUME.md) because retrieved text goes to a hosted LLM.

## 1e: coverage audit
- v1 ([coverage_audit_v1.md](coverage_audit_v1.md)): sampled closed issues → 76% weren't questions. Invalid design.
- v2 ([coverage_audit_v2.md](coverage_audit_v2.md)): 45 real answered questions → **54% strict, ~72% incl. partial**.
  Gaps: ros2_control (fixable), niche ecosystems, and ~14% irreducible new expert answers.
- Fix applied: **added ros2_control** (4 repos: 357 doc files over jazzy/rolling/lyrical + 2,056 closed issues).
- Target revised: measure Recall@10 ≥ 80% on *answerable* questions end-to-end in Stage 7.

## Carried into Stage 2
- Noise: Isaac Sim `THIRD_PARTY_NOTICE.md`, `skills/*/SKILL.md` and `.claude/skills/*` agent files,
  `.github/` / `.docker/` files in ros2_control repos.
- Apply `fix_html_entities` + `ros_generation` to Stack Exchange; HTML → text for web pages.

**Stage 1 status: DONE.**
