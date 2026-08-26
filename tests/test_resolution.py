"""Key lookup: dp[...] and dp.get(...)."""

from __future__ import annotations

from pathlib import Path

import pytest

from datapaths.exceptions import ArtifactError


@pytest.fixture
def populated(repo):
    repo.write_registry(
        {
            "features_train_v02": {
                "type": "features",
                "root": "features",
                "path": "features/features_train_v02.parquet",
                "format": "parquet",
                "hash": "sha256:deadbeef",
                "tags": ["v02"],
                "notes": "a note about bazin",
                "updated_at": "2026-02-01T00:00:00+00:00",
            }
        }
    )
    return repo


class TestGetItem:
    def test_root_prefix_returns_the_storage_root(self, populated):
        dp = populated.dp()
        assert dp["root_features"] == populated.roots["features"]

    def test_bare_root_name_also_works(self, populated):
        dp = populated.dp()
        assert dp["features"] == populated.roots["features"]

    def test_artifact_name_resolves_to_an_absolute_path(self, populated):
        dp = populated.dp()
        expected = populated.roots["features"] / "features" / "features_train_v02.parquet"
        assert dp["features_train_v02"] == expected.resolve()

    def test_a_root_name_shadows_an_artifact_of_the_same_name(self, populated):
        """Lookup order is root_-prefix, then roots, then the registry.

        An artifact literally named "features" is therefore unreachable via
        dp[...] while a root of that name exists. Pinned because a refactor
        that reorders these branches changes what existing code resolves to
        without raising anywhere.
        """
        reg = populated.read_registry_raw()["artifacts"]
        reg["features"] = {
            "type": "misc",
            "root": "misc",
            "path": "features.json",
            "format": "json",
        }
        populated.write_registry(reg)
        dp = populated.dp()
        assert dp["features"] == populated.roots["features"]

    @pytest.mark.parametrize("key", ["nope", "root_nope", ""])
    def test_unknown_keys_raise_keyerror(self, populated, key):
        with pytest.raises(KeyError):
            populated.dp()[key]

    def test_record_naming_an_absent_root_raises(self, repo):
        repo.write_registry(
            {"orphan": {"type": "misc", "root": "vanished", "path": "x.json", "format": "json"}}
        )
        with pytest.raises(ArtifactError, match="vanished"):
            repo.dp()["orphan"]

    def test_record_without_a_path_raises(self, repo):
        repo.write_registry({"pathless": {"type": "misc", "root": "misc", "format": "json"}})
        with pytest.raises(ArtifactError, match="no path field"):
            repo.dp()["pathless"]


class TestGet:
    def test_returns_the_whole_record_by_default(self, populated):
        rec = populated.dp().get("features_train_v02")
        assert rec["format"] == "parquet"
        assert rec["hash"] == "sha256:deadbeef"

    def test_returned_record_is_a_copy(self, populated):
        dp = populated.dp()
        dp.get("features_train_v02")["format"] = "mutated"
        assert dp.get("features_train_v02")["format"] == "parquet"

    def test_missing_key_returns_the_default(self, populated):
        assert populated.dp().get("nope") is None
        assert populated.dp().get("nope", "fallback") == "fallback"

    @pytest.mark.parametrize("field", ["path_abs", "absolute_path"])
    def test_path_abs_aliases_render_an_absolute_string(self, populated, field):
        got = populated.dp().get("features_train_v02", field=field)
        assert Path(got).is_absolute()
        assert got.endswith("features/features_train_v02.parquet")

    def test_named_field_falls_back_to_the_default(self, populated):
        dp = populated.dp()
        assert dp.get("features_train_v02", field="format") == "parquet"
        assert dp.get("features_train_v02", "none", field="absent") == "none"


class TestReload:
    def test_reload_picks_up_a_registry_written_by_someone_else(self, repo):
        dp = repo.dp()
        assert dp.get("late") is None
        repo.write_registry(
            {"late": {"type": "misc", "root": "misc", "path": "late.json", "format": "json"}}
        )
        dp.reload()
        assert dp.get("late") is not None

    def test_absent_registry_is_an_empty_catalogue_not_an_error(self, repo):
        assert repo.registry_file.exists() is False
        assert repo.dp().catalogues == {}
