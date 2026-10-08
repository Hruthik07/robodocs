"""Stage 1c: collect Stack Exchange Q&A (source D9): questions + answers + comments.

Output, one raw JSON file per question (answers and comments embedded):
    data/raw/stackexchange/<site>[__<tag>]/<question_id>.json
    data/raw/stackexchange/<site>[__<tag>]/_state.json         <- resume checkpoint

Run it with:
    conda run -n robodocs python -m robodocs.collect.stackexchange
    conda run -n robodocs python -m robodocs.collect.stackexchange --site stackoverflow
    conda run -n robodocs python -m robodocs.collect.stackexchange --force

Three API tricks used here:
  1. A custom *filter* makes /questions return each question WITH its answers and comments
     (as markdown). Without it you'd need extra calls per question.
  2. Paging by date ("give me 100 questions created at/after T") instead of page=1,2,3...:
     deep page numbers get slow and limited; a date cursor never does.
  3. Obey `backoff`: if the API says "wait N seconds", we wait, or the key gets throttled.
"""

import argparse
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm import tqdm

from robodocs.config import StackExchangeSource, get_settings

API = "https://api.stackexchange.com/2.3"
PAGE_SIZE = 100  # API maximum

# Fields added on top of the defaults (title, tags, score, is_answered, accepted_answer_id,
# link, creation_date, owner, ...). body_markdown keeps code blocks as markdown.
FILTER_INCLUDE = [
    "question.body_markdown", "question.answers", "question.comments",
    "answer.body_markdown", "answer.comments", "answer.link",
    "comment.body_markdown",
]


class TransientError(Exception):
    """Worth retrying: network errors, 5xx, throttling."""


# ---------------------------------------------------------------------------
# Small pure helpers (tested in tests/test_collect_stackexchange.py)
# ---------------------------------------------------------------------------

def source_dir_name(src: StackExchangeSource) -> str:
    """robotics -> 'robotics'; stackoverflow + ros2 -> 'stackoverflow__ros2'."""
    return f"{src.site}__{src.tag}" if src.tag else src.site


def next_cursor(fromdate: int, page: int, items: list[dict]) -> tuple[int, int]:
    """Where to continue after receiving `items` (sorted by creation_date ascending).

    Normal case: move the date cursor to the newest creation_date we saw, back to page 1.
    The boundary question gets fetched twice, and that's harmless because files are keyed by id.

    Edge case: all 100 items share the SAME timestamp as the cursor (bulk imports do this).
    Moving the date wouldn't progress, so stay on that date and go to the next page.
    """
    newest = max(i["creation_date"] for i in items)
    if newest > fromdate:
        return newest, 1
    return fromdate, page + 1


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

@retry(retry=retry_if_exception_type(TransientError),
       wait=wait_exponential(multiplier=2, min=4, max=120),
       stop=stop_after_attempt(5), reraise=True)
def api_get(session: requests.Session, path: str, params: dict) -> dict:
    try:
        r = session.get(f"{API}{path}", params=params, timeout=60)
    except requests.RequestException as e:
        raise TransientError(f"network: {e}") from e

    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code >= 500 or data.get("error_name") == "throttle_violation":
        raise TransientError(f"HTTP {r.status_code} {data.get('error_message', '')}")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {data.get('error_message', r.text[:200])}")

    if data.get("backoff"):  # the API asks us to pause before the next call to this method
        time.sleep(data["backoff"])
    return data


def create_filter(session: requests.Session) -> str:
    """Ask the API for a filter id that includes answers/comments/markdown bodies."""
    data = api_get(session, "/filters/create",
                   {"include": ";".join(FILTER_INCLUDE), "base": "default", "unsafe": "false"})
    return data["items"][0]["filter"]


# ---------------------------------------------------------------------------
# Collection loop for one source
# ---------------------------------------------------------------------------

def collect_source(session: requests.Session, src: StackExchangeSource, key: str,
                   filter_id: str, out_root: Path, force: bool = False) -> dict:
    out_dir = out_root / source_dir_name(src)
    state_path = out_dir / "_state.json"
    if force and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    state = (json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists()
             else {"site": src.site, "tag": src.tag, "fromdate": 0, "page": 1, "done": False})
    if state["done"]:
        return state

    params = {"site": src.site, "pagesize": PAGE_SIZE, "sort": "creation", "order": "asc",
              "filter": filter_id, "key": key}
    if src.tag:
        params["tagged"] = src.tag

    bar = tqdm(desc=source_dir_name(src), unit="q", leave=False,
               initial=sum(1 for _ in out_dir.glob("[0-9]*.json")))
    while True:
        data = api_get(session, "/questions",
                       {**params, "fromdate": state["fromdate"], "page": state["page"]})
        items = data.get("items", [])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        new = 0
        for q in items:
            path = out_dir / f"{q['question_id']}.json"
            new += not path.exists()
            q["_meta"] = {"source": "stackexchange", "site": src.site, "query_tag": src.tag,
                          "collected_at": now}
            path.write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")
        bar.update(new)

        state["quota_remaining"] = data.get("quota_remaining")
        if not data.get("has_more") or not items:
            state.update(done=True, completed_at=now)
        else:
            state["fromdate"], state["page"] = next_cursor(state["fromdate"], state["page"], items)
        state["collected"] = sum(1 for _ in out_dir.glob("[0-9]*.json"))
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        if state["done"]:
            bar.close()
            return state
        if (state["quota_remaining"] or 0) < 20:
            raise RuntimeError("daily API quota nearly used up; re-run tomorrow to resume")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Stack Exchange Q&A (Stage 1c)")
    parser.add_argument("--site", help="only this site, e.g. robotics")
    parser.add_argument("--force", action="store_true", help="discard progress and start over")
    args = parser.parse_args()

    settings = get_settings()
    out_root = settings.abs_path(settings.paths.raw_data) / "stackexchange"
    key = os.environ.get("STACKEXCHANGE_KEY", "").strip()
    if not key:
        raise SystemExit("STACKEXCHANGE_KEY missing in .env (without it: only 300 calls/day)")

    sources = [s for s in settings.collection.stackexchange.sources
               if not args.site or s.site == args.site]
    session = requests.Session()
    filter_id = create_filter(session)

    failures = []
    for src in sources:
        try:
            st = collect_source(session, src, key, filter_id, out_root, force=args.force)
            print(f"{source_dir_name(src):28} {st['collected']:6} questions  done={st['done']}  "
                  f"(quota left {st.get('quota_remaining')})")
        except Exception as e:
            failures.append(source_dir_name(src))
            print(f"{source_dir_name(src):28} FAILED: {e}")

    if failures:
        print(f"\nFAILED (re-run to resume): {', '.join(failures)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
