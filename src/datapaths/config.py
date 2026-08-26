from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import warnings
import yaml

from .exceptions import ConfigError, ConfigWarning

DEFAULT_ROOTS_FILE = "configs/roots.local.yaml"
DEFAULT_REGISTRY_FILE = "configs/artifacts_registry.yaml"

# Environment overrides. Each may hold an absolute path (used as-is) or a path
# relative to the repository root (resolved against it), so a repo that does not
# follow the configs/ convention can say so without changing any call site.
ENV_REPO_ROOT = "DATAPATHS_REPO_ROOT"
ENV_ROOTS_FILE = "DATAPATHS_ROOTS_FILE"
ENV_REGISTRY_FILE = "DATAPATHS_REGISTRY_FILE"

# Appended to both the warning and the error below. An entry gets dropped only
# when the file is malformed, and by then the reader is looking at YAML that
# seemed fine to them -- so name the mistakes that actually produce this rather
# than only reporting that something was wrong.
_ROOTS_SHAPE_HINT = """
A roots file maps each root name to one absolute path, with nothing nested:

    features: /mnt/scratch/features
    data: /mnt/scratch/data

Most likely causes, in rough order:
  - everything is indented under a top-level key. The registry file nests its
    contents under 'artifacts:'; the roots file has no such wrapper.
  - a value is a list ('- /mnt/...') or is split across lines.
  - a key was left with an empty value.
  - $DATAPATHS_ROOTS_FILE (or the roots_file argument) points at a different
    file -- the registry, or another project's config."""


@dataclass(frozen=True)
class DatapathsConfig:
    roots_file: Path
    registry_file: Path


def find_repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists() or (p / ".git").exists():
            return p
    raise ConfigError(
        "Cannot detect repository root (no pyproject.toml or .git found).\n"
        f"Run from the repository root, set ${ENV_REPO_ROOT}, or pass "
        "repo_root=Path(...) explicitly."
    )


def _env_path(name: str) -> Path | None:
    """Read an env var as a path, treating unset and empty alike."""
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def _resolve_against(repo_root: Path, value: str | Path) -> Path:
    """Absolute values win outright; relative ones hang off the repo root."""
    p = Path(value).expanduser()
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def resolve_repo_root(repo_root: Path | None = None) -> Path:
    """Precedence: explicit argument, then $DATAPATHS_REPO_ROOT, then discovery.

    Discovery walks up from the *current working directory*, which is why the
    env var matters: a notebook or a job started elsewhere would otherwise find
    whichever repository happens to be above it.
    """
    if repo_root is not None:
        return Path(repo_root).expanduser().resolve()
    from_env = _env_path(ENV_REPO_ROOT)
    if from_env is not None:
        rr = from_env.resolve()
        if not rr.is_dir():
            raise ConfigError(f"${ENV_REPO_ROOT} is not a directory: {rr}")
        return rr
    return find_repo_root()


def load_config(
    repo_root: Path | None = None,
    roots_file: str | Path | None = None,
    registry_file: str | Path | None = None,
) -> DatapathsConfig:
    """Locate the two config files this package reads.

    For each file the precedence is: explicit argument, then the environment
    override, then the ``configs/`` default. Passing an argument explicitly is
    therefore never overridden by an env var that happens to be set in the
    shell -- the caller who names a file means it.
    """
    rr = resolve_repo_root(repo_root)

    roots = roots_file if roots_file is not None else _env_path(ENV_ROOTS_FILE)
    if roots is None:
        roots = DEFAULT_ROOTS_FILE

    registry = registry_file if registry_file is not None else _env_path(ENV_REGISTRY_FILE)
    if registry is None:
        registry = DEFAULT_REGISTRY_FILE

    return DatapathsConfig(
        roots_file=_resolve_against(rr, roots),
        registry_file=_resolve_against(rr, registry),
    )


def _warn_on_colliding_roots(roots: dict[str, Path], roots_file: Path) -> None:
    """Flag roots that are harder to tell apart than their names suggest.

    Two separate checks, and only the second is a correctness matter:

    * Names differing only in case. Lookup is exact, so these really are two
      roots and nothing breaks -- but dp["Features"] then fails while
      "features" exists, and tags are lowercased everywhere else, so the
      inconsistency invites a typo that surfaces as a bare KeyError.
    * Two names pointing at one directory. This one bites: both roots build
      canonical paths under the same tree, so two artifacts can land on the
      same file and archive over each other, and verify calls both OK until
      they do. samefile() settles it whatever the cause -- an identical path, a
      symlink, a bind mount, or a case-insensitive filesystem.
    """
    by_fold: dict[str, list[str]] = {}
    for name in roots:
        by_fold.setdefault(name.casefold(), []).append(name)
    for group in by_fold.values():
        if len(group) > 1:
            warnings.warn(
                f"Root names differing only in case in {roots_file}: "
                f"{', '.join(repr(g) for g in sorted(group))}. Lookup is exact, so "
                f"these are separate roots -- but a lookup that gets the case wrong "
                f"fails rather than falling back. Rename one unless the distinction "
                f"is deliberate.",
                ConfigWarning,
                stacklevel=3,
            )

    names = sorted(roots)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = roots[a], roots[b]
            same = pa == pb
            if not same and pa.exists() and pb.exists():
                try:
                    same = pa.samefile(pb)
                except OSError:
                    same = False
            if same:
                warnings.warn(
                    f"Roots {a!r} and {b!r} in {roots_file} are the same directory "
                    f"({pa}). Artifacts of both will share one tree, so two records "
                    f"can resolve to the same file and overwrite each other with no "
                    f"warning from verify.",
                    ConfigWarning,
                    stacklevel=3,
                )
            elif str(pa).casefold() == str(pb).casefold() and not (
                pa.exists() and pb.exists()
            ):
                # Both existing and not samefile would have proved them distinct;
                # since at least one is absent, only the filesystem can say.
                warnings.warn(
                    f"Roots {a!r} and {b!r} in {roots_file} have paths differing only "
                    f"in case ({pa}, {pb}). On a case-insensitive filesystem these are "
                    f"one directory, and artifacts of both would share it.",
                    ConfigWarning,
                    stacklevel=3,
                )


def load_roots(cfg: DatapathsConfig) -> dict[str, Path]:
    if not cfg.roots_file.exists():
        raise ConfigError(
            f"roots file not found at {cfg.roots_file}. "
            f"Create it (not committed) with absolute paths, or point "
            f"${ENV_ROOTS_FILE} at one that exists."
        )
    data = yaml.safe_load(cfg.roots_file.read_text()) or {}
    if not isinstance(data, dict) or not data:
        raise ConfigError(f"Invalid roots file: {cfg.roots_file}")
    roots: dict[str, Path] = {}
    skipped: list[str] = []
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, (str, Path)):
            skipped.append(f"{k!r} ({type(v).__name__})")
            continue
        roots[k] = Path(v).expanduser().resolve()

    if skipped and not roots:
        # Nothing survived, so the file's shape is wrong rather than one line of
        # it. Refusing here beats returning {} and surfacing a bare KeyError at
        # the first lookup, with nothing to connect it back to this file.
        raise ConfigError(
            f"No usable roots in {cfg.roots_file}: "
            f"{'the only entry was' if len(skipped) == 1 else f'all {len(skipped)} entries were'}"
            f" skipped ({', '.join(skipped)})."
            + _ROOTS_SHAPE_HINT
        )
    if skipped:
        # Some roots loaded, so a session that does not need the broken ones can
        # continue -- but not silently.
        warnings.warn(
            f"Skipped {len(skipped)} unusable "
            f"{'entry' if len(skipped) == 1 else 'entries'} in {cfg.roots_file}: "
            f"{', '.join(skipped)}. Loaded: {', '.join(sorted(roots))}."
            + _ROOTS_SHAPE_HINT,
            ConfigWarning,
            stacklevel=2,
        )

    _warn_on_colliding_roots(roots, cfg.roots_file)
    return roots
