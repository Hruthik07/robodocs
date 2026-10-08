"""Stage 1a-web: collect docs that exist only as a website (source D5), e.g. Isaac Sim.

For every (site, version) in config/settings.yaml:
  1. download the site's Sphinx `searchindex.js` -> the complete list of pages
     (no link-crawling needed, and nothing gets missed),
  2. download every page as raw HTML into  data/raw/web/<framework>/<version>/<page path>
  3. write                                  data/raw/web/<framework>/<version>/manifest.json

Run it with:
    conda run -n robodocs python -m robodocs.collect.website
    conda run -n robodocs python -m robodocs.collect.website --force

Resumable: pages already on disk are skipped; the manifest is written last.
Polite: one request every `delay_seconds`; checks robots.txt before crawling.
"""

import argparse
import json
import shutil
import time
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from tqdm import tqdm

from robodocs.config import WebDocsSite, get_settings

USER_AGENT = "robodocs-collector (personal learning project)"


class TransientError(Exception):
    pass


# ---------------------------------------------------------------------------
# Pure helpers (tested in tests/test_collect_website.py)
# ---------------------------------------------------------------------------

def parse_sphinx_index(js_text: str) -> list[str]:
    """Return the sorted list of page paths (e.g. 'installation/install_python.html').

    Handles both formats seen in the wild:
      - standard Sphinx:  Search.setIndex({"docnames": ["a/b", ...], ...})
      - NVIDIA theme:     const searchData = {"data": [{"filename": "a/b.html#anchor", ...}]}
    """
    obj, _ = json.JSONDecoder().raw_decode(js_text[js_text.index("{"):])
    if "docnames" in obj:
        pages = {f"{name}.html" for name in obj["docnames"]}
    elif "data" in obj:
        pages = {e["filename"].split("#")[0] for e in obj["data"] if e.get("filename")}
    else:
        raise ValueError(f"Unknown search index format, keys: {list(obj)[:5]}")
    return sorted(p for p in pages if p and not p.startswith(("http://", "https://")))


def page_url(base_url: str, version_path: str, page: str) -> str:
    return f"{base_url.rstrip('/')}/{version_path.strip('/')}/{page.lstrip('/')}"


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

@retry(retry=retry_if_exception_type(TransientError),
       wait=wait_exponential(multiplier=2, min=2, max=60),
       stop=stop_after_attempt(4), reraise=True)
def fetch(session: requests.Session, url: str) -> requests.Response:
    try:
        r = session.get(url, timeout=60)
    except requests.RequestException as e:
        raise TransientError(str(e)) from e
    if r.status_code >= 500 or r.status_code == 429:
        raise TransientError(f"HTTP {r.status_code}")
    return r


def robots_allows(session: requests.Session, base_url: str, url: str) -> bool:
    """No robots.txt (404) = no restrictions, which is the standard interpretation."""
    r = fetch(session, f"{base_url.rstrip('/')}/robots.txt")
    if r.status_code != 200 or "user-agent" not in r.text.lower():
        return True
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def collect_site_version(session: requests.Session, site: WebDocsSite, version: str,
                         version_path: str, out_root: Path, delay: float,
                         force: bool = False) -> dict:
    target = out_root / site.framework / version
    manifest_path = target / "manifest.json"
    if manifest_path.exists() and not force:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    if force and target.exists():
        shutil.rmtree(target)

    index_url = page_url(site.base_url, version_path, "searchindex.js")
    if not robots_allows(session, site.base_url, index_url):
        raise RuntimeError(f"robots.txt disallows {index_url}")
    resp = fetch(session, index_url)
    resp.raise_for_status()
    pages = parse_sphinx_index(resp.text)

    files, missing = [], []
    for page in tqdm(pages, desc=f"{site.framework} {version}", unit="page", leave=False):
        url = page_url(site.base_url, version_path, page)
        dest = target / page
        if not dest.exists():  # resume: skip pages we already have
            r = fetch(session, url)
            time.sleep(delay)
            if r.status_code != 200:
                missing.append({"page": page, "status": r.status_code})
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.content)
        files.append({"path": page, "url": url, "bytes": dest.stat().st_size})

    manifest = {
        "framework": site.framework, "version": version, "base_url": site.base_url,
        "version_path": version_path, "source": "website",
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "page_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
        "missing": missing, "files": files,
    }
    target.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect website-only docs (Stage 1a-web)")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    cfg = settings.collection.web_docs
    out_root = settings.abs_path(settings.paths.raw_data) / "web"
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    failures = []
    for site in cfg.sites:
        for version, vpath in site.versions.items():
            try:
                m = collect_site_version(session, site, version, vpath, out_root,
                                         cfg.delay_seconds, force=args.force)
                print(f"{site.framework:10} {version:6} {m['page_count']:5} pages "
                      f"{m['total_bytes'] / 1e6:6.1f} MB  missing={len(m['missing'])}")
            except Exception as e:
                failures.append(f"{site.framework} {version}")
                print(f"{site.framework:10} {version:6} FAILED: {e}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
