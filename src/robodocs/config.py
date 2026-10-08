"""Load settings.yaml into typed, validated objects.

Why pydantic instead of a plain dict?
- A typo like `settings["colection"]` fails late and silently with a dict.
- With pydantic, a bad/missing config value fails immediately at startup
  with a clear error, and your editor autocompletes `settings.collection...`.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "settings.yaml"


class PathsConfig(BaseModel):
    raw_data: Path
    processed_data: Path


class DocsSource(BaseModel):
    framework: str
    repo: str                    # "owner/name" on GitHub
    versions: dict[str, str]     # version label -> git branch or tag
    paths: list[str]             # folders inside the repo that hold the docs
    name: str | None = None      # output folder; needed when several repos share a framework

    @property
    def folder(self) -> str:
        return self.name or self.framework


class WebDocsSite(BaseModel):
    framework: str
    base_url: str
    versions: dict[str, str]     # version label -> URL path segment


class WebDocsConfig(BaseModel):
    delay_seconds: float
    sites: list[WebDocsSite]


class NotesConfig(BaseModel):
    root: Path                   # "~" allowed: expanded to the user's home folder

    @field_validator("root")
    @classmethod
    def _expand_home(cls, v: Path) -> Path:
        return v.expanduser()
    folders: list[str]
    include: list[str]
    exclude_names: list[str] = []
    exclude_dirs: list[str] = []


class GitHubRepo(BaseModel):
    repo: str                    # "owner/name"
    framework: str
    discussions: bool = False    # collect Discussions too (only if the repo has them enabled)


class GitHubConfig(BaseModel):
    page_size: int
    repos: list[GitHubRepo]


class StackExchangeSource(BaseModel):
    site: str                    # API site name, e.g. "robotics", "stackoverflow"
    tag: str | None = None       # None = whole site


class StackExchangeConfig(BaseModel):
    sources: list[StackExchangeSource]


class CollectionConfig(BaseModel):
    docs: list[DocsSource]
    docs_file_extensions: list[str]
    web_docs: WebDocsConfig
    notes: NotesConfig
    github: GitHubConfig
    stackexchange: StackExchangeConfig


class Settings(BaseModel):
    paths: PathsConfig
    collection: CollectionConfig

    def abs_path(self, p: Path) -> Path:
        """Resolve a config path relative to the project root."""
        return p if p.is_absolute() else PROJECT_ROOT / p


@lru_cache
def get_settings() -> Settings:
    """Load once, reuse everywhere (lru_cache makes this a cheap singleton)."""
    load_dotenv(PROJECT_ROOT / ".env")
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return Settings.model_validate(yaml.safe_load(f))
