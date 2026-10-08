# RoboDocs: Requirements & Scope

**Status:** Draft v1 · 2026-10-07 · Owner: Gali Hruthik
**Type:** Learning project (end-to-end RAG), built to be used for real by its first user.

---

## 1. Problem statement

Robotics developers lose hours every week searching for answers to **errors, version breakages and
configuration questions**. The answers usually exist, but they are:

- **scattered** across official docs, GitHub issues, discussions, release notes, Q&A forums and the team's own notes;
- **version-specific**: ROS 2 distros, Isaac Sim / Isaac Lab and MuJoCo change APIs between releases;
- **misreported by general AI assistants**, which mix versions and confidently produce outdated code.

**RoboDocs** is a version-aware question-answering assistant. A developer asks a question or pastes an
error; RoboDocs retrieves only from the relevant framework and version, answers, and **cites the exact
doc / issue / note** it used. If the sources don't cover the question, it says so.

### Not solved by this project (explicitly)
Sim-to-real tuning, automated robot testing, rosbag/log analysis. These are real pains but not
retrieval problems.

## 2. Users

| Persona | Need | Example |
|---|---|---|
| **Sim / RL developer** (primary; the project owner) | Fix Isaac Sim / Isaac Lab / MuJoCo errors fast | "`No module named omni.isaac.core` on Isaac Sim 5" |
| **ROS 2 application developer** | Navigation / manipulation config and API answers | "What does `inflation_radius` do in Nav2?" |
| **New team member** | Find how the team solved things before | "How did we fix headless rendering on EC2?" |

## 3. Use cases (MVP)

| ID | Use case | Input | Expected output |
|---|---|---|---|
| UC1 | Error → fix | Error message / traceback (+ optional version) | Likely cause + fix + links to matching issues/docs |
| UC2 | Version-correct how-to | Question + framework/version | Steps/code from that version's docs only |
| UC3 | Migration | "X in 4.5 → what in 5.x?" | Before/after from release notes / changelogs |
| UC4 | Config lookup | Parameter name / config question | Meaning, default, guidance, doc link |
| UC5 | Team knowledge | Question about own past work | Answer from `my_notes/` with file reference |

---

## 4. Data requirements

### 4.1 Sources (measured 2026-10-07)

| # | Source | Content | Volume (measured) | License | Access |
|---|---|---|---|---|---|
| D1 | `ros2/ros2_documentation` | ROS 2 official docs (branch per distro) | 338 rst/md files, 5.1 MB | CC-BY-4.0 | git clone |
| D2 | `ros-navigation/docs.nav2.org` | Nav2 docs incl. parameter reference | 273 files, 1.7 MB | (see repo) | git clone |
| D3 | `isaac-sim/IsaacLab` `docs/` | Isaac Lab docs | 256 files, 2.2 MB | BSD-3 | git clone |
| D4 | `isaac-sim/IsaacSim` | Isaac Sim repo markdown (READMEs, changelogs) | 962 files, 4.6 MB | NVIDIA | git clone |
| D5 | Isaac Sim docs site | Official Isaac Sim user/API docs (HTML) | TBD in Stage 1 (site reachable) | NVIDIA | polite HTML crawl |
| D6 | `google-deepmind/mujoco` `doc/` | MuJoCo docs + changelog | 45 files, 2.1 MB | Apache-2.0 | git clone |
| D7 | GitHub **closed issues** + comments | Real problems + confirmed fixes | IsaacLab 2,491 · IsaacSim 462 · MuJoCo 1,790 · Nav2 2,600 · MoveIt2 1,091 · rclcpp 705 · rclpy 326 · rosbag2 670 · geometry2 192 · ros2_documentation 496 → **~10,800** | GitHub ToS (link + attribute) | GraphQL API |
| D8 | GitHub **Discussions** (answered) | Q&A with accepted answer | IsaacLab 157 · IsaacSim 89 · MuJoCo 173 → **~420** | GitHub ToS | GraphQL API |
| D9 | **Robotics Stack Exchange** (incl. migrated ROS Answers) | Q&A with accepted answers | 46,955 questions, ~39,700 accepted answers; `ros2` tag 3,869 | CC BY-SA 4.0 | StackExchange API |
| D10 | `my_notes/` | Owner's own project notes (ISSAC, pybullet, embodied records) | ~10–50 files | Own | local folder |
| D11 | Release notes / changelogs | Version migration info | Inside D1–D6 | as source | parsed from D1–D6 |

### 4.2 Data quantity: what "sufficient" means

For RAG, **coverage beats volume.** More data is only better if it contains the answers.
The corpus is sufficient when:

| Criterion | Target | How we check |
|---|---|---|
| **Coverage** | ≥ 80% of 50 *held-out recent* issues have their answer somewhere in the corpus | Manual check in Stage 1 (coverage audit) |
| **Balance** | Every framework in scope has docs + issues + Q&A | Per-source counts report |
| **Versions** | Every in-scope version has its own docs | Version metadata on 100% of doc chunks |
| **Quality** | ≥ 90% of kept issues/Q&A contain a resolution | Filter rules + 50-item manual sample |
| **Freshness** | Data ≤ 30 days old at eval time; incremental refresh works | `collected_at` metadata |

### 4.3 Expected corpus after filtering (estimate)

| Source group | Raw | After quality filter (est.) |
|---|---|---|
| Docs (D1–D6, D11) | ~2,000 files | ~1,800 docs → ~10k chunks |
| GitHub issues (D7) | ~10,800 | ~4,000–5,500 (resolved, with a fix in comments) |
| Discussions (D8) | ~420 | ~400 |
| Robotics SE (D9), tag-filtered to in-scope stack | ~10–12k | ~6,000–8,000 (accepted answer, score ≥ 0) |
| Own notes (D10) | 10–50 | all |
| **Total** | | **~12k–16k documents → ~40k–70k chunks** |

That size runs fine on a laptop: local embedding on CPU takes about 20–40 minutes, and the vector DB is a few hundred MB.

### 4.4 Data quality rules (Stage 1–2)
- **Issues:** keep closed issues that have ≥ 1 comment and are not `wontfix/duplicate/stale`. Prefer issues closed by a PR or with maintainer reply. Drop bot-only threads.
- **Q&A:** keep only questions with an accepted answer or answer score ≥ 1.
- **Docs:** strip navigation/boilerplate; keep code blocks intact; keep headings as structure.
- **Dedup:** exact + near-duplicate removal (same issue mirrored in forum, repeated doc pages across versions keep both but tagged by version).
- **PII:** keep only usernames already public; no emails.

### 4.5 Metadata schema (every document)
`doc_id, source_type (doc|issue|discussion|qa|note), framework (ros2|nav2|moveit2|isaac_sim|isaac_lab|mujoco),
version, title, url, created_at, updated_at, collected_at, resolved (bool), labels/tags, license`

### 4.6 Collection constraints
| Constraint | Detail | Mitigation |
|---|---|---|
| GitHub rate limit | 5,000 requests/hr (authenticated, `gh` already logged in) | GraphQL: issues + comments in one query, 50 per page → ~250 calls total |
| StackExchange rate limit | 300 req/day without key; 10,000 with a free key | Register a free API key; `pagesize=100` |
| Website crawl (D5) | Must be polite | robots.txt, 1 req/s, cache every page to disk |
| Re-runs | Collection must be resumable | Raw JSON cached per item; skip if exists |
| Licensing | Mixed licenses | Personal/learning use; **raw data never committed**; every answer links to the original source |

---

## 5. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR1 | Collect all sources in §4.1 into `data/raw/` with a resumable CLI | Must |
| FR2 | Parse & normalize into one `Document` format with §4.5 metadata | Must |
| FR3 | Content-aware chunking (docs by heading, issues by Q/A thread, code blocks unsplit) | Must |
| FR4 | Embed and index chunks in a local vector DB | Must |
| FR5 | Hybrid retrieval (BM25 + vector) with metadata filters (framework, version, source_type) | Must |
| FR6 | Reranking of top candidates | Should |
| FR7 | Answer generation with inline citations to retrieved sources | Must |
| FR8 | Refuse / say "not found" when retrieved context doesn't support an answer | Must |
| FR9 | Detect framework/version from the question when not given | Should |
| FR10 | Pluggable LLM behind one interface, provider/model chosen by config (see §7.1) | Must |
| FR11 | Incremental ingestion: add new issues / notes without full rebuild | Should |
| FR12 | REST API (`/ask`) + simple chat UI | Must |
| FR13 | Query log: question, retrieved chunks, scores, latency, tokens | Must |

## 6. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR1 | Runs locally on Windows laptop, CPU-only acceptable | — |
| NFR2 | Latency (cloud LLM) | p95 < 8 s; first token < 2 s with streaming |
| NFR3 | Cost | < $0.01 per query; total project LLM spend < $15 |
| NFR4 | Reproducibility | One command each: collect, ingest, eval |
| NFR5 | Config-driven | All tunables in `config/settings.yaml`; secrets in `.env` |
| NFR6 | Tested | Unit tests for parsers, chunkers, retrieval filters |

## 7. Success metrics & evaluation

**Eval set:** about 150 questions:
- ~100 from **held-out real closed issues / accepted Q&A** (question → known fix), *excluded from the index*;
- ~30 version-specific how-to / migration questions (hand-written, checked against docs);
- ~20 **unanswerable** questions (to test refusal).

| Metric | Target |
|---|---|
| Retrieval Recall@10 | ≥ 80% |
| Answer correctness (LLM-judge + 30-item manual check) | ≥ 70% |
| **Version correctness** (no wrong-version APIs) | ≥ 90% |
| Faithfulness (answer supported by cited sources) | ≥ 90% |
| Correct refusal on unanswerable | ≥ 85% |
| **Beats plain LLM baseline** on correctness + version correctness | Yes, on the same eval set |

### 7.1 LLM strategy (decided 2026-10-07)

**Open-source first, swap only if the numbers say so.**

- **Hardware constraint:** dev laptop has no GPU (Intel Core 7 150U, 16 GB RAM), so large open
  models can't run locally. Open-weight models are used through a **hosted, OpenAI-compatible API**
  (Groq / OpenRouter / Together, free tier first). Candidate class: largest open-weight models
  available at Stage 6 (e.g. Llama 70B-class, Qwen3, gpt-oss-120b, DeepSeek); final pick made then.
- **Embeddings:** open-source, run locally (e.g. a BGE / E5 / nomic model) — no API needed.
- **Code design:** one `LLMClient` interface. Every OpenAI-compatible provider is a config change;
  Claude gets its own adapter. Swapping models must require **zero pipeline code changes**.
- **Decision rule (Stage 7):** run the full eval with the open model.
  - Meets all §7 targets → **keep the open model**.
  - Misses targets → first check whether **retrieval** is the cause (Recall@10). If retrieval is
    fine and generation fails (correctness / faithfulness / refusal), **swap to a frontier model
    (Claude)**, re-run the same eval, and record the comparison.
- **Judge model:** LLM-as-judge scoring uses a model different from the one being evaluated,
  plus a 30-item manual check, to avoid a model grading its own answers.

---

## 8. Scope

### In scope (MVP)
- Frameworks: **ROS 2 (+ Nav2, MoveIt 2, ros2_control), Isaac Sim, Isaac Lab, MuJoCo**
  (ros2_control added 2026-10-07 after coverage audit v2)
- Versions: the **two most recent major versions** of each (exact list fixed in Stage 1 from repo tags/branches)
- All sources D1–D11, use cases UC1–UC5, FR1–FR13
- Local vector DB, local embeddings, pluggable LLM, FastAPI + Streamlit

### Out of scope (MVP)
- Gazebo, Webots, PyBullet docs (easy to add later via same collectors)
- Hardware datasheet PDFs (stretch: hard table parsing)
- Image / video content, voice
- Multi-turn agent, automatic code execution
- Cloud deployment, auth, multi-user
- Log/rosbag analysis, sim-to-real tuning

---

## 9. Plan & effort (part-time ~10–12 h/week)

| Stage | Deliverable | Est. hours |
|---|---|---|
| 0 | Setup: env, structure, config | 1 (mostly done) |
| **1** | **Data collection**: 4 collectors (git docs, GitHub GraphQL, StackExchange, web crawl) + coverage audit | **12–15** |
| 2 | Parsing & cleaning: unified `Document`, filters, dedup | 8–10 |
| 3 | Chunking: content-aware strategies + comparison | 5–6 |
| 4 | Embeddings + vector DB | 4–5 |
| 5 | Retrieval: vector, BM25, hybrid, filters, rerank | 8–10 |
| 6 | Generation: prompts, citations, refusal, pluggable LLM | 6–8 |
| 7 | Evaluation: eval set, metrics, LLM + baseline comparison | 10–12 |
| 8 | API + UI | 5–6 |
| 9 | Incremental ingestion + polish (README, diagram, results) | 5–6 |
| | **Total** | **~65–80 h → 7–8 weeks** (+20% learning buffer → 8–10 weeks) |

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Issues are noisy (no clear fix) | Bad answers | Resolution filters + manual sample audit |
| Version metadata missing on issues/Q&A | Version-wrong answers | Infer from labels/text/date; mark `version=unknown`, rank lower |
| Isaac Sim docs crawl blocked / changes | Gap in key source | Repo markdown (D4) + Isaac Lab docs as fallback |
| Eval leakage (eval issues also indexed) | Inflated scores | Hold out eval items by ID before indexing |
| Corpus too large for laptop | Slow iteration | Dev subset (10%) for iteration, full set for final eval |
| Scope creep | Never finish | §8 is the contract; new ideas go to "Phase 2" list |

## 11. Open decisions
1. ~~LLM choice~~ → decided: open-source via hosted API first (§7.1). Free Groq/OpenRouter key needed by Stage 6.
2. Register a free StackExchange API key (needed for D9 volume).
3. Confirm frameworks in §8 (add/remove any?).
