"""Shared fixtures.

Everything here builds a throwaway repository under tmp_path: a marker file so
root discovery has something to find, a roots file pointing at temporary
storage, and a cwd inside it. No test touches a real repository or a real data
root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import textwrap

import pytest
import yaml

from datapaths import Datapaths
from datapaths.config import ENV_REGISTRY_FILE, ENV_REPO_ROOT, ENV_ROOTS_FILE

ROOT_KEYS = ("data", "features", "models", "predictions", "misc")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every override so the developer's shell cannot reach the suite.

    Autouse and unconditional: a DATAPATHS_ROOTS_FILE exported for real work
    would otherwise make these tests pass or fail depending on who runs them,
    which is precisely the failure mode the env vars introduced.
    """
    for var in (ENV_REPO_ROOT, ENV_ROOTS_FILE, ENV_REGISTRY_FILE):
        monkeypatch.delenv(var, raising=False)
    # updated_by falls back to $USER; pin it so records are comparable.
    monkeypatch.setenv("USER", "tester")
    monkeypatch.delenv("USERNAME", raising=False)


class Repo:
    """Handle on a temporary repository and its storage roots."""

    def __init__(self, root: Path, roots: dict[str, Path]) -> None:
        self.root = root
        self.roots = roots

    @property
    def roots_file(self) -> Path:
        return self.root / "configs" / "roots.local.yaml"

    @property
    def registry_file(self) -> Path:
        return self.root / "configs" / "artifacts_registry.yaml"

    def dp(self, **kwargs: Any) -> Datapaths:
        return Datapaths(**kwargs)

    def write_roots(self, mapping: dict[str, Any]) -> None:
        self.roots_file.parent.mkdir(parents=True, exist_ok=True)
        self.roots_file.write_text(yaml.safe_dump({k: str(v) for k, v in mapping.items()}))

    def write_registry(self, artifacts: dict[str, Any], version: int = 1) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.registry_file.write_text(
            yaml.safe_dump({"registry_version": version, "artifacts": artifacts})
        )

    def read_registry_raw(self) -> dict[str, Any]:
        if not self.registry_file.exists():
            return {}
        return yaml.safe_load(self.registry_file.read_text()) or {}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    """A repo with a pyproject marker, five storage roots, and cwd inside it."""
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "consumer"\n')

    store = tmp_path / "store"
    roots = {k: store / k for k in ROOT_KEYS}
    for p in roots.values():
        p.mkdir(parents=True)

    r = Repo(root, roots)
    r.write_roots(roots)
    monkeypatch.chdir(root)
    return r


@pytest.fixture
def dp(repo: Repo) -> Datapaths:
    return repo.dp()


@pytest.fixture
def frame():
    """A small DataFrame; skips the test if the tabular extra is absent."""
    pd = pytest.importorskip("pandas")
    return pd.DataFrame({"id": [1, 2, 3], "flux": [0.5, 1.5, 2.5]})


@pytest.fixture
def bare_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A directory with no pyproject.toml and no .git anywhere above it.

    tmp_path itself sits under /tmp, which has no repository markers, so root
    discovery genuinely fails here rather than finding the suite's own repo.
    """
    d = tmp_path / "nowhere" / "deeper"
    d.mkdir(parents=True)
    monkeypatch.chdir(d)
    return d
