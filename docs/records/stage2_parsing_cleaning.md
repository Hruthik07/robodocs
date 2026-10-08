# Stage 2: Parsing & cleaning (record)

**Date:** 2026-10-07 · **Status:** done · **Output:** `data/processed/documents.jsonl` (+ `report.json`, `sample.md`)
**Run:** `python -m robodocs.process.run` (~2 min) · **Tests:** 57 passing

## What it does
5 raw formats → one `Document` contract (`process/schema.py`): stable `doc_id`, `source_type`, `framework`,
`version`, `ros_generation`, clean Markdown `text`, citation `url`, dates, quality signals
(`resolved`, `has_accepted_answer`, `closed_by_pr`, `maintainer_answered`, `score`), `content_hash`.

| Module | Job |
|---|---|
| `rst.py` | RST → Markdown; directive handling built from a frequency survey of the corpus; resolves `.. include::` |
| `html.py` | Sphinx website article → Markdown (bs4 + markdownify, no identifier escaping) |
| `text.py` | shared cleaning: protects code fences, trims huge logs (keeps error lines), images → `[image: alt](url)`, strips logos/badges/emails/HTML comments, MkDocs syntax |
| `version.py` | version from tags → template/text patterns → else `unknown` (never guessed) |
| `parsers.py` | one parser per source; every drop has a recorded reason |
| `run.py` | dedup (id / exact text / same question moved issue↔discussion), report, random sample |

## Result: 66,768 raw → 61,606 documents

| Source | Raw | Kept | Main drop reasons |
|---|---|---|---|
| git docs | 3,308 | 2,680 | too_short 427 (empty API stubs/index pages), noise 176, include fragments 25 |
| web docs | 791 | 785 | too_short 6 |
| notes | 15 | 15 | |
| GitHub issues | 12,885 | 11,242 | no_answer 1,307, not_planned_unanswered 176, moved/duplicate 126 |
| GitHub discussions | 2,175 | 1,408 | no_answer 420, exact_duplicate 197, same_question_elsewhere 150 |
| Stack Exchange | 47,594 | 45,476 | no_answer 2,088 |

Q&A generation labels: ros1 27,334 · ros2 4,549 · both 97 · unknown 13,496 (mostly non-ROS robotics).
Version known: issues 3,416 / 11,242 · discussions 463 / 1,408 · Q&A 12,085 / 45,476.

## Bugs found by checking real output (not by unit tests)
| Found | Fix |
|---|---|
| ROS 2 install pages had empty "Set locale" / "Enable repositories" sections | resolve `.. include::` from the downloaded repo |
| `sudo apt install ros-{DISTRO}-desktop` | fill Sphinx placeholders per version (`{DISTRO}` → `jazzy`, 360 uses) |
| ~800 links with `{REPOS_FILE_BRANCH}` in ros2_control docs | fill with the file's git ref |
| "Replaced by isaacsim.core.api" note dropped as too short | keep short deprecation/rename notes (it answers a top error) |
| Stack Exchange code is 4-space indented, not fenced | convert to fences so chunking never splits code |
| `[Originally posted](…)` ROS Answers boilerplate survived | regex accepts the link form |
| Issue-template `## Bug report` headings clash with thread structure | demote user headings to bold |
| "humble opinion" / "soldering iron" would match ROS distros | distro in free text requires ROS context; template forms (`ROS2 Version:\n- Humble`) supported |
| `isaaclab\_ov`, BOM, `:github_url:` fields in RST | unescape, strip BOM, drop Sphinx file metadata |
| markdownify escaped `ROS\_GenericPub` | escaping off (identifiers must match exactly) |

## Known limits / decisions for later stages
- **27k ROS 1 Q&A documents are kept but labelled**; whether they enter the index (and how they rank) is a
  Stage 4/5 decision. They are ~45% of the text volume (216 MB total), which matters for CPU embedding time.
- GitHub `authorAssociation` sometimes shows core developers as `CONTRIBUTOR`, so `maintainer_answered`
  under-counts.
- `literalinclude` / `mujoco-include` content is a placeholder (source files not collected).
- Images: alt text + link only (multimodal is out of scope).
