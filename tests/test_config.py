"""Config resolution: repo-root discovery, env overrides, precedence.

The precedence rule under test throughout is, per setting independently:
explicit argument > environment variable > configs/ default.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from datapaths.config import (
    DEFAULT_REGISTRY_FILE,
    DEFAULT_ROOTS_FILE,
    ENV_REGISTRY_FILE,
    ENV_REPO_ROOT,
    ENV_ROOTS_FILE,
    find_repo_root,
    load_config,
    load_roots,
    resolve_repo_root,
)
from datapaths.exceptions import ConfigError, ConfigWarning


class TestDefaults:
    def test_defaults_land_under_configs(self, repo):
        cfg = load_config()
        assert cfg.roots_file == (repo.root / DEFAULT_ROOTS_FILE).resolve()
        assert cfg.registry_file == (repo.root / DEFAULT_REGISTRY_FILE).resolve()

    def test_discovery_walks_up_from_a_subdirectory(self, repo, monkeypatch):
        deep = repo.root / "notebooks" / "03_experiments"
        deep.mkdir(parents=True)
        monkeypatch.chdir(deep)
        assert load_config().roots_file == (repo.root / DEFAULT_ROOTS_FILE).resolve()

    def test_git_dir_alone_is_enough(self, tmp_path, monkeypatch):
        root = tmp_path / "gitonly"
        (root / ".git").mkdir(parents=True)
        monkeypatch.chdir(root)
        assert find_repo_root() == root.resolve()


class TestEnvOverrides:
    def test_relative_roots_file_resolves_against_repo_root(self, repo, monkeypatch):
        monkeypatch.setenv(ENV_ROOTS_FILE, "etc/roots.yaml")
        assert load_config().roots_file == (repo.root / "etc" / "roots.yaml").resolve()

    def test_absolute_roots_file_is_used_as_is(self, repo, monkeypatch, tmp_path):
        elsewhere = tmp_path / "shared" / "roots.yaml"
        monkeypatch.setenv(ENV_ROOTS_FILE, str(elsewhere))
        assert load_config().roots_file == elsewhere.resolve()

    def test_registry_file_override_is_independent_of_roots(self, repo, monkeypatch):
        monkeypatch.setenv(ENV_REGISTRY_FILE, "etc/registry.yaml")
        cfg = load_config()
        assert cfg.registry_file == (repo.root / "etc" / "registry.yaml").resolve()
        assert cfg.roots_file == (repo.root / DEFAULT_ROOTS_FILE).resolve()

    def test_repo_root_override_works_from_an_unrelated_cwd(self, repo, monkeypatch, tmp_path):
        away = tmp_path / "somewhere-else"
        away.mkdir()
        monkeypatch.chdir(away)
        monkeypatch.setenv(ENV_REPO_ROOT, str(repo.root))
        assert load_config().roots_file == (repo.root / DEFAULT_ROOTS_FILE).resolve()

    def test_repo_root_override_expands_user(self, repo, monkeypatch):
        monkeypatch.setenv("HOME", str(repo.root.parent))
        monkeypatch.setenv(ENV_REPO_ROOT, f"~/{repo.root.name}")
        assert resolve_repo_root() == repo.root.resolve()

    @pytest.mark.parametrize("var", [ENV_REPO_ROOT, ENV_ROOTS_FILE, ENV_REGISTRY_FILE])
    def test_empty_string_is_treated_as_unset(self, repo, monkeypatch, var):
        monkeypatch.setenv(var, "   ")
        cfg = load_config()
        assert cfg.roots_file == (repo.root / DEFAULT_ROOTS_FILE).resolve()
        assert cfg.registry_file == (repo.root / DEFAULT_REGISTRY_FILE).resolve()


class TestPrecedence:
    """An argument the caller passes is never overridden by the environment."""

    def test_argument_beats_env_for_roots_file(self, repo, monkeypatch):
        monkeypatch.setenv(ENV_ROOTS_FILE, "from/env.yaml")
        cfg = load_config(roots_file="from/arg.yaml")
        assert cfg.roots_file == (repo.root / "from" / "arg.yaml").resolve()

    def test_argument_beats_env_for_registry_file(self, repo, monkeypatch):
        monkeypatch.setenv(ENV_REGISTRY_FILE, "from/env.yaml")
        cfg = load_config(registry_file="from/arg.yaml")
        assert cfg.registry_file == (repo.root / "from" / "arg.yaml").resolve()

    def test_argument_beats_env_for_repo_root(self, repo, monkeypatch, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv(ENV_REPO_ROOT, str(other))
        assert load_config(repo_root=repo.root).roots_file.parent.parent == repo.root.resolve()

    def test_settings_are_resolved_independently(self, repo, monkeypatch):
        """Pinning one file must not disable the override on the other."""
        monkeypatch.setenv(ENV_ROOTS_FILE, "env/roots.yaml")
        monkeypatch.setenv(ENV_REGISTRY_FILE, "env/registry.yaml")
        cfg = load_config(roots_file="arg/roots.yaml")
        assert cfg.roots_file == (repo.root / "arg" / "roots.yaml").resolve()
        assert cfg.registry_file == (repo.root / "env" / "registry.yaml").resolve()

    def test_datapaths_init_does_not_shadow_the_env(self, repo, monkeypatch):
        """Datapaths() with no arguments must let the env vars through.

        Regression guard: the constructor used to repeat the configs/ defaults
        as its own default arguments, which reached load_config as explicit
        values and silently beat every override.
        """
        alt = repo.root / "etc" / "roots.yaml"
        alt.parent.mkdir(parents=True)
        alt.write_text("features: /tmp/elsewhere\n")
        monkeypatch.setenv(ENV_ROOTS_FILE, "etc/roots.yaml")
        assert repo.dp().cfg.roots_file == alt.resolve()


class TestFailures:
    def test_no_marker_anywhere_raises(self, bare_dir):
        with pytest.raises(ConfigError, match="Cannot detect repository root"):
            load_config()

    def test_error_message_names_the_env_var(self, bare_dir):
        with pytest.raises(ConfigError, match=ENV_REPO_ROOT):
            load_config()

    def test_repo_root_pointing_at_a_file_raises(self, repo, monkeypatch):
        monkeypatch.setenv(ENV_REPO_ROOT, str(repo.root / "pyproject.toml"))
        with pytest.raises(ConfigError, match="not a directory"):
            load_config()

    def test_missing_roots_file_raises_and_names_the_env_var(self, repo):
        repo.roots_file.unlink()
        with pytest.raises(ConfigError, match=ENV_ROOTS_FILE):
            load_roots(load_config())

    @pytest.mark.parametrize("body", ["- a\n- b\n", "", "just a string\n"])
    def test_malformed_roots_file_raises(self, repo, body):
        repo.roots_file.write_text(body)
        with pytest.raises(ConfigError, match="Invalid roots file"):
            load_roots(load_config())


class TestLoadRoots:
    def test_paths_are_absolute_and_user_expanded(self, repo, monkeypatch):
        monkeypatch.setenv("HOME", "/home/someone")
        repo.write_roots({"features": "~/features", "data": "/abs/data"})
        roots = load_roots(load_config())
        assert roots["features"] == Path("/home/someone/features")
        assert roots["data"] == Path("/abs/data")

    def test_malformed_entries_are_skipped_not_fatal(self, repo):
        """A nested or non-string entry is dropped, and the rest still load.

        Deliberate: a hand-edited roots file with one bad line should not take
        the whole session down when the root the caller wants is fine. It is
        not silent, though -- see TestRootsFileDiagnostics.
        """
        repo.roots_file.write_text(
            "features: /abs/features\n"
            "broken:\n"
            "  nested: /abs/nope\n"
            "also_broken: [1, 2]\n"
        )
        with pytest.warns(ConfigWarning):
            roots = load_roots(load_config())
        assert roots == {"features": Path("/abs/features")}


class TestRootsFileDiagnostics:
    """What the reader is told when a roots file is malformed.

    A dropped entry only happens when the file is wrong, and by then the author
    is looking at YAML that seemed fine to them. These pin that the diagnostic
    names the offending key and points at the likely cause, because a message
    saying only "something was skipped" leaves them no better off.
    """

    def test_partial_damage_warns_and_names_the_bad_key(self, repo):
        repo.roots_file.write_text("features: /abs/features\nmodels:\n")
        with pytest.warns(ConfigWarning, match="'models'") as record:
            load_roots(load_config())
        assert len(record) == 1

    def test_warning_reports_the_parsed_type(self, repo):
        repo.roots_file.write_text("features: /abs/features\nmodels: [/a, /b]\n")
        with pytest.warns(ConfigWarning, match="list"):
            load_roots(load_config())

    def test_warning_says_what_did_load(self, repo):
        repo.roots_file.write_text("features: /abs/f\ndata: /abs/d\nmodels:\n")
        with pytest.warns(ConfigWarning, match="Loaded: data, features"):
            load_roots(load_config())

    def test_warning_names_the_file(self, repo):
        repo.roots_file.write_text("features: /abs/features\nmodels:\n")
        with pytest.warns(ConfigWarning, match=re.escape(str(repo.roots_file))):
            load_roots(load_config())

    def test_warning_suggests_causes(self, repo):
        repo.roots_file.write_text("features: /abs/features\nmodels:\n")
        with pytest.warns(ConfigWarning, match="indented under a top-level key"):
            load_roots(load_config())

    def test_a_wholly_nested_file_raises_instead_of_loading_nothing(self, repo):
        """The mistake this exists for: one extra level of indentation.

        It is an easy one to make, because the registry file really does nest
        everything under 'artifacts:'. Returning {} here would surface as a
        bare KeyError at the first lookup, with nothing pointing back at the
        roots file.
        """
        repo.roots_file.write_text(
            "roots:\n  features: /abs/features\n  data: /abs/data\n"
        )
        with pytest.raises(ConfigError, match="No usable roots"):
            load_roots(load_config())

    def test_that_error_explains_the_nesting(self, repo):
        repo.roots_file.write_text("roots:\n  features: /abs/features\n")
        with pytest.raises(ConfigError, match="no such wrapper"):
            load_roots(load_config())

    def test_that_error_names_the_offending_key(self, repo):
        repo.roots_file.write_text("roots:\n  features: /abs/features\n")
        with pytest.raises(ConfigError, match=re.escape("'roots' (dict)")):
            load_roots(load_config())

    def test_singular_phrasing_for_one_entry(self, repo):
        repo.roots_file.write_text("roots:\n  features: /abs/features\n")
        with pytest.raises(ConfigError, match="the only entry was skipped"):
            load_roots(load_config())

    def test_plural_phrasing_for_several(self, repo):
        repo.roots_file.write_text("first:\n  a: 1\nsecond:\n  b: 2\n")
        with pytest.raises(ConfigError, match="all 2 entries were skipped"):
            load_roots(load_config())

    def test_a_clean_file_warns_about_nothing(self, repo, recwarn):
        load_roots(load_config())
        assert [w for w in recwarn if issubclass(w.category, ConfigWarning)] == []
