# Coverage audit v1 (2026-10-07)

**Sample:** 50 GitHub issues closed 2026-04-07 or later, `stateReason=COMPLETED`, ≥2 comments, no feature labels,
seed 42, quotas isaac_lab 12 · isaac_sim 8 · mujoco 10 · nav2 10 · moveit2 5 · ros2 5.
**Search:** SQLite FTS5 / BM25 over 64,355 docs, restricted to content created before the issue,
plus targeted manual queries for ambiguous cases. Evidence: `data/index/audit_cases.jsonl`.

## Verdicts

| Verdict | Cases | Count |
|---|---|---|
| covered | 5, 38 | 2 |
| partial | 3, 7, 8, 31, 34, 36, 49 | 7 |
| gap | 2, 10, 22 | 3 |
| not answerable by any corpus: novel bug fixed in code, unresolved, or not a question (chore / feature request / release request / doc edit) | 1, 4, 6, 9, 11–21, 23–30, 32, 33, 35, 37, 39–48, 50 | 38 |

**Coverage on answerable cases:** (2 + 0.5·7) / 12 = **46%** (target ≥ 80%). **n = 12 is too small to conclude anything.**

## Findings
1. **The sample was the wrong proxy.** 76% of recently closed issues are bugs fixed in code, chores, or
   feature requests: nothing a knowledge base can answer. The sample-design filter was too weak.
   Fix → v2 samples *questions* (answered Discussions, accepted Stack Exchange answers, `question`-labelled issues).
2. **For Isaac Sim, bugs dominate.** The useful answer is often "known bug, fixed in version X";
   the per-extension CHANGELOGs we collected are the right source for that.
3. **Keyword search finds related threads but often not the exact fix** (cases 3, 8, 31, 49).
   Expected to improve with hybrid retrieval in Stage 5; v1 under-estimates.
4. Noise spotted: Isaac Lab / MuJoCo repos contain `skills/*/SKILL.md` and `.claude/skills/*` agent files
   in the docs corpus; filter in Stage 2.
