from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
from filelock import FileLock

from .exceptions import RegistryError

@dataclass
class Registry:
    version: int
    artifacts: dict[str, dict[str, Any]]

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def read_registry(path: Path) -> Registry:
    if not path.exists():
        # initialize minimal registry
        return Registry(version=1, artifacts={})
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        raise RegistryError(f"Registry is not a dict: {path}")
    version = int(raw.get("registry_version", 1))
    artifacts = raw.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise RegistryError(f"'artifacts' must be a dict: {path}")
    return Registry(version=version, artifacts=artifacts)

def write_registry(path: Path, reg: Registry) -> None:
    _ensure_parent(path)
    payload = {"registry_version": reg.version, "artifacts": reg.artifacts}
    path.write_text(yaml.safe_dump(payload, sort_keys=True, allow_unicode=True))

def update_registry_atomic(path: Path, fn) -> Registry:
    """
    Lock registry file, read, apply fn(reg) -> reg, write, return reg.
    """
    _ensure_parent(path)
    lock = FileLock(str(path) + ".lock")
    with lock:
        reg = read_registry(path)
        reg2 = fn(reg)
        if not isinstance(reg2, Registry):
            raise RegistryError("Registry update function must return Registry")
        write_registry(path, reg2)
        return reg2
