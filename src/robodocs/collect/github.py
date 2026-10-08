"""Stage 1b: collect closed GitHub issues and Discussions (sources D7-D8) via GraphQL.

Output, one raw JSON file per item (untouched API data + a `_meta` block):
    data/raw/github/<owner>__<repo>/issues/<number>.json
    data/raw/github/<owner>__<repo>/discussions/<number>.json
    data/raw/github/<owner>__<repo>/<kind>/_state.json      <- resume checkpoint

Run it with:
    conda run -n robodocs python -m robodocs.collect.github
    conda run -n robodocs python -m robodocs.collect.github --repo google-deepmind/mujoco
    conda run -n robodocs python -m robodocs.collect.github --kind discussions
    conda run -n robodocs python -m robodocs.collect.github --force     # start over

Why GraphQL and not the REST API?
  REST: 1 call for a page of issues + 1 call PER ISSUE for its comments -> ~11,000 calls.
  GraphQL: issues AND their comments in one request -> ~450 calls for everything.
"""

import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm import tqdm

from robodocs.config import GitHubRepo, get_settings

GRAPHQL_URL = "https://api.github.com/graphql"

# What we ask for per closed issue. Comments carry the fix; `closer` tells us if a PR
# or commit closed it (a strong "this was really fixed" signal for Stage 2 filtering).
ISSUES_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    items: issues(states: CLOSED, first: $first, after: $after,
                  orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body url createdAt updatedAt closedAt stateReason
        author { login }
        labels(first: 20) { nodes { name } }
        reactions { totalCount }
        comments(first: 100) {
          totalCount
          nodes { body createdAt authorAssociation author { login } reactions { totalCount } }
        }
        timelineItems(itemTypes: [CLOSED_EVENT], last: 1) {
          nodes {
            ... on ClosedEvent {
              createdAt
              closer {
                __typename
                ... on PullRequest { number url title }
                ... on Commit { oid url }
              }
            }
          }
        }
      }
    }
  }
}
"""

# Discussions: Q&A threads. `answer` is the comment the asker marked as the solution.
DISCUSSIONS_QUERY = """
query($owner: String!, $name: String!, $first: Int!, $after: String) {
  rateLimit { cost remaining resetAt }
  repository(owner: $owner, name: $name) {
    items: discussions(first: $first, after: $after,
                       orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body url createdAt updatedAt isAnswered closed upvoteCount
        author { login }
        category { name isAnswerable }
        labels(first: 20) { nodes { name } }
        answer { body createdAt authorAssociation author { login } upvoteCount }
        comments(first: 50) {
          totalCount
          nodes {
            body createdAt authorAssociation isAnswer upvoteCount author { login }
            replies(first: 20) {
              totalCount
              nodes { body createdAt authorAssociation author { login } }
            }
          }
        }
      }
    }
  }
}
"""

QUERIES = {"issues": ISSUES_QUERY, "discussions": DISCUSSIONS_QUERY}


class TransientError(Exception):
    """Worth retrying: timeouts, 5xx, secondary rate limits."""


# ---------------------------------------------------------------------------
# Small pure helpers (tested in tests/test_collect_github.py)
# ---------------------------------------------------------------------------

def repo_dir_name(repo: str) -> str:
    """'isaac-sim/IsaacLab' -> 'isaac-sim__IsaacLab' (a '/' can't be in a folder name)."""
    return repo.replace("/", "__")


def get_token() -> str:
    """GITHUB_TOKEN from .env if set, otherwise borrow the token of the logged-in `gh` CLI."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        return token
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit("No GitHub token: set GITHUB_TOKEN in .env or run `gh auth login`.")


def seconds_until(iso_ts: str) -> float:
    """Seconds from now until an ISO timestamp like '2026-10-07T19:00:00Z' (never negative)."""
    reset = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    return max(0.0, (reset - datetime.now(timezone.utc)).total_seconds())


# ---------------------------------------------------------------------------
# API call: retries + rate-limit handling live here, so the loop below stays simple
# ---------------------------------------------------------------------------

@retry(retry=retry_if_exception_type(TransientError),
       wait=wait_exponential(multiplier=2, min=4, max=60),
       stop=stop_after_attempt(4), reraise=True)
def graphql(session: requests.Session, query: str, variables: dict) -> dict:
    try:
        r = session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=60)
    except requests.RequestException as e:
        raise TransientError(f"network: {e}") from e

    if r.status_code >= 500 or r.status_code in (403, 429):
        # 502/504 = GitHub gave up on a heavy query; 403/429 = secondary rate limit.
        wait = int(r.headers.get("Retry-After", 0))
        if wait:
            time.sleep(wait)
        raise TransientError(f"HTTP {r.status_code}")
    r.raise_for_status()

    payload = r.json()
    if payload.get("errors"):
        if any(e.get("type") == "RATE_LIMITED" for e in payload["errors"]):
            raise TransientError("RATE_LIMITED")
        raise RuntimeError(f"GraphQL error: {payload['errors'][0].get('message')}")

    data = payload["data"]
    # Primary rate limit: 5,000 points/hour. If we're nearly out, sleep until the reset.
    rl = data["rateLimit"]
    if rl["remaining"] < 50:
        pause = seconds_until(rl["resetAt"]) + 5
        tqdm.write(f"  rate limit nearly used up, sleeping {pause / 60:.1f} min")
        time.sleep(pause)
    return data


# ---------------------------------------------------------------------------
# Collection loop for one (repo, kind)
# ---------------------------------------------------------------------------

def collect_kind(session: requests.Session, cfg: GitHubRepo, kind: str, out_root: Path,
                 page_size: int, force: bool = False) -> dict:
    """Page through all items of `kind` ('issues' | 'discussions') for one repo.

    Resumable: after every page we save the GraphQL cursor in _state.json.
    Crash at page 200 -> re-run continues at page 201.
    """
    kind_dir = out_root / repo_dir_name(cfg.repo) / kind
    state_path = kind_dir / "_state.json"
    if force and kind_dir.exists():
        shutil.rmtree(kind_dir)
    kind_dir.mkdir(parents=True, exist_ok=True)

    state = (json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists()
             else {"repo": cfg.repo, "kind": kind, "cursor": None, "collected": 0, "done": False})
    if state["done"]:
        return state

    owner, name = cfg.repo.split("/")
    first = page_size
    bar = tqdm(desc=f"{cfg.repo} {kind}", unit="item", initial=state["collected"], leave=False)

    while True:
        variables = {"owner": owner, "name": name, "first": first, "after": state["cursor"]}
        try:
            data = graphql(session, QUERIES[kind], variables)
        except TransientError:
            # Some pages hold huge issues (pasted logs) and GitHub times out.
            # Asking for fewer items per request usually fixes it.
            if first <= 5:
                raise
            first //= 2
            tqdm.write(f"  {cfg.repo} {kind}: page too heavy, retrying with {first} per page")
            continue

        conn = data["repository"]["items"]
        bar.total = conn["totalCount"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for node in conn["nodes"]:
            node["_meta"] = {"source": f"github_{kind}", "repo": cfg.repo,
                             "framework": cfg.framework, "collected_at": now}
            (kind_dir / f"{node['number']}.json").write_text(
                json.dumps(node, ensure_ascii=False), encoding="utf-8")

        # Items first, cursor second: a crash in between just re-writes the same files.
        state.update(cursor=conn["pageInfo"]["endCursor"], total=conn["totalCount"],
                     collected=state["collected"] + len(conn["nodes"]))
        bar.update(len(conn["nodes"]))
        if not conn["pageInfo"]["hasNextPage"]:
            state.update(done=True, completed_at=now)
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

        if state["done"]:
            bar.close()
            return state
        first = page_size  # recover from a temporary halving


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect GitHub issues + discussions (Stage 1b)")
    parser.add_argument("--repo", help="only this repo, e.g. google-deepmind/mujoco")
    parser.add_argument("--kind", choices=["issues", "discussions", "all"], default="all")
    parser.add_argument("--force", action="store_true", help="discard progress and start over")
    args = parser.parse_args()

    settings = get_settings()
    gh = settings.collection.github
    out_root = settings.abs_path(settings.paths.raw_data) / "github"

    repos = [r for r in gh.repos if not args.repo or r.repo == args.repo]
    if not repos:
        raise SystemExit(f"No repo {args.repo!r} in settings.yaml")

    session = requests.Session()
    session.headers.update({"Authorization": f"bearer {get_token()}",
                            "User-Agent": "robodocs-collector"})

    failures = []
    for cfg in repos:
        kinds = ["issues", "discussions"] if cfg.discussions else ["issues"]
        for kind in kinds:
            if args.kind not in ("all", kind):
                continue
            try:
                st = collect_kind(session, cfg, kind, out_root, gh.page_size, force=args.force)
                print(f"{cfg.repo:30} {kind:12} {st['collected']:6} items  done={st['done']}")
            except Exception as e:  # keep going with the other repos
                failures.append(f"{cfg.repo} {kind}")
                print(f"{cfg.repo:30} {kind:12} FAILED: {e}")

    if failures:
        print(f"\nFAILED (re-run to resume): {', '.join(failures)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
