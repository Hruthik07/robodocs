"""Stage 1a: collect official documentation (sources D1-D6) from git repos.

For every (framework, version) in config/settings.yaml this module:
  1. shallow-clones ONLY the doc files of the repo at that git ref (branch/tag),
  2. copies them into   data/raw/docs/<framework>/<version>/<original path in repo>
  3. writes             data/raw/docs/<framework>/<version>/manifest.json

Run it with:
    conda run -n robodocs python -m robodocs.collect.docs
    conda run -n robodocs python -m robodocs.collect.docs --framework mujoco   # just one
    conda run -n robodocs python -m robodocs.collect.docs --force              # re-download

Why git and not scraping the docs website?
  The repo holds the *source* of the docs (.rst/.md): clean text, real headings,
  code blocks intact, and one branch/tag per version, which is version metadata for free.
  A website gives you HTML soup and usually only the latest version.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from robodocs.config import DocsSource, get_settings


# ---------------------------------------------------------------------------
# Small pure helpers: no network, easy to unit test (tests/test_collect_docs.py)
# ---------------------------------------------------------------------------

def build_sparse_patterns(paths: list[str], extensions: list[str]) -> list[str]:
    """Build git sparse-checkout patterns that match ONLY doc files.

    Example:
        build_sparse_patterns(["docs"], [".md", ".rst"])
        -> ["/docs/**/*.md", "/docs/**/*.rst"]

        build_sparse_patterns(["."], [".md"])          # "." = whole repo
        -> ["/**/*.md"]

    Why: big repos (Isaac Sim, MuJoCo) contain meshes, binaries, test assets.
    These patterns make git download only the doc files: seconds, not minutes.
    """
    patterns = []
    for path in paths:
        prefix = "" if path in (".", "") else "/" + path.strip("/")
        for ext in extensions:
            patterns.append(f"{prefix}/**/*{ext}")
    return patterns


def github_blob_url(repo: str, ref: str, path_in_repo: str) -> str:
    """URL of one file on GitHub, used later for CITATIONS in answers.

    Example:
        github_blob_url("google-deepmind/mujoco", "3.15.0", "doc/overview.rst")
        -> "https://github.com/google-deepmind/mujoco/blob/3.15.0/doc/overview.rst"

    Watch out: on Windows, paths use backslashes. URLs must use forward slashes.
    """
    path = path_in_repo.replace("\\", "/").lstrip("/")
    return f"https://github.com/{repo}/blob/{ref}/{path}"


# ---------------------------------------------------------------------------
# The real work
# ---------------------------------------------------------------------------

def _git(*args: str) -> str:
    """Run one git command; raise with git's own error message if it fails."""
    # core.longpaths: some doc trees exceed Windows' 260-char path limit.
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} ... failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def sparse_clone(repo: str, ref: str, patterns: list[str], dest: Path) -> str:
    """Shallow, sparse clone of `repo` at `ref` into `dest`. Returns the commit SHA.

    --depth 1          only the latest commit, no history
    --filter=blob:none don't download file contents until needed
    --no-checkout +    then sparse-checkout decides which files actually get downloaded
    sparse-checkout
    Recording the commit SHA makes the dataset reproducible: you know exactly what you indexed.
    """
    _git("clone", "--depth", "1", "--branch", ref, "--filter=blob:none", "--no-checkout",
         f"https://github.com/{repo}.git", str(dest))
    _git("-C", str(dest), "sparse-checkout", "set", "--no-cone", *patterns)
    _git("-C", str(dest), "checkout", ref)
    return _git("-C", str(dest), "rev-parse", "HEAD")


def collect_version(source: DocsSource, version: str, ref: str,
                    out_root: Path, extensions: list[str], force: bool = False) -> dict:
    """Collect one (framework, version) and return its manifest.

    Resumable: if the manifest already exists we skip the download (unless force).
    """
    target = out_root / source.folder / version
    manifest_path = target / "manifest.json"

    if manifest_path.exists() and not force:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    if target.exists():
        shutil.rmtree(target)  # partial/old download: start clean

    patterns = build_sparse_patterns(source.paths, extensions)
    files = []
    # Clone into a temp dir that is deleted automatically. ignore_cleanup_errors:
    # on Windows git leaves read-only files that would otherwise crash the cleanup.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        clone_dir = Path(tmp) / "repo"
        commit_sha = sparse_clone(source.repo, ref, patterns, clone_dir)

        for f in sorted(clone_dir.rglob("*")):
            rel = f.relative_to(clone_dir)
            if not f.is_file() or ".git" in rel.parts or f.suffix.lower() not in extensions:
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            rel_posix = rel.as_posix()
            files.append({
                "path": rel_posix,
                "url": github_blob_url(source.repo, ref, rel_posix),
                "bytes": f.stat().st_size,
            })

    manifest = {
        "framework": source.framework,
        "version": version,
        "repo": source.repo,
        "ref": ref,
        "commit_sha": commit_sha,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_bytes": sum(x["bytes"] for x in files),
        "files": files,
    }
    # Written LAST: its presence means "this version is complete" (that's what makes resume safe).
    target.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect official docs (Stage 1a)")
    parser.add_argument("--framework", help="only collect this framework, e.g. mujoco")
    parser.add_argument("--force", action="store_true", help="re-download even if already collected")
    args = parser.parse_args()

    settings = get_settings()
    out_root = settings.abs_path(settings.paths.raw_data) / "docs"
    exts = [e.lower() for e in settings.collection.docs_file_extensions]

    sources = [s for s in settings.collection.docs if not args.framework or args.framework in (s.framework, s.folder)]
    if not sources:
        raise SystemExit(f"No docs source named {args.framework!r} in settings.yaml")

    total_files, failures = 0, []
    for source in sources:
        for version, ref in source.versions.items():
            try:
                m = collect_version(source, version, ref, out_root, exts, force=args.force)
            except Exception as e:  # one bad ref/network blip must not kill the whole run
                failures.append(f"{source.folder} {version}")
                print(f"{source.folder:18} {version:8} FAILED: {e}")
                continue
            total_files += m["file_count"]
            print(f"{source.folder:18} {version:8} {m['file_count']:5} files "
                  f"{m['total_bytes'] / 1e6:6.1f} MB   (commit {m['commit_sha'][:7]})")

    print(f"\nTotal: {total_files} files" + (f" | FAILED: {', '.join(failures)}" if failures else ""))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
