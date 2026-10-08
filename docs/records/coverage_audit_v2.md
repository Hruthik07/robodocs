# Coverage audit v2: real questions (2026-10-07)

**Why v2:** v1 sampled closed issues; 76% weren't questions (code-fixed bugs, chores, feature requests).
**Sample:** 45 questions asked 2025-10-01 or later, each with a confirmed answer: answered GitHub Discussions,
`[Question]` issues answered by a maintainer, Stack Exchange accepted answers. Seed 42. Quotas
isaac_lab 10 · isaac_sim 8 · mujoco 8 (pool had only 8) · ros2 12 · nav2 6 · moveit2 1 (pool had only 1).
**Search:** FTS5/BM25, only content created before the question + targeted queries. Evidence: `data/index/audit_v2_cases.jsonl`.

## Verdicts

| Verdict | Cases | Count |
|---|---|---|
| covered | 2, 4, 9, 10, 12, 13, 23, 24, 26, 27, 33, 37, 45 | 13 |
| partial | 3, 5, 7, 8, 11, 14, 17, 19, 22, 25, 28, 31, 39 | 13 |
| gap | 1, 15, 18, 20, 21, 29, 30, 32, 35, 36 | 10 |
| excluded (no real answer given / out of scope / tool bug) | 6, 16, 34, 38, 40, 41, 42, 43, 44 | 9 |

**Coverage = (13 + 0.5·13) / 36 = 54%** (target 80%).

## Gap analysis

| Gap type | Cases | Fixable by more data? |
|---|---|---|
| **ros2_control** (controllers, hardware interfaces, demos): docs + issues not collected | 29, 30, 36 | **Yes**: ros-controls repos (~2,070 closed issues + docs) |
| micro-ROS, TurtleBot 2 on ROS 2 (niche ecosystems) | 32, 35 | Partly; low priority |
| Expert reasoning that only exists in the maintainer's reply (PD/timestep limit cycles, Replicator write-back, LiDAR vs mirrors, MuJoCo frames, new tactile flag) | 1, 15, 18, 20, 21 | **No**: no corpus contains it before it's written |

## Conclusions
1. **Data is good for the core use cases.** Coverage of covered + partial ≈ 72%; most partials are
   *search quality* (related thread found, exact fix ranked low), which Stage 5 hybrid retrieval targets.
2. **One fixable source gap: ros2_control.** It is the #1 ROS 2 pain area in the gaps (3 of 10).
3. **~14% of real questions (5/36) are irreducible**: new expert answers. 80% strict coverage is not
   reachable by any corpus; the system's correct behaviour there is to say "not found" (FR8).
4. Revised target proposal: measure end-to-end in Stage 7 (Recall@10 ≥ 80% on *answerable* questions),
   instead of strict keyword coverage here.
