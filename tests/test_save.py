"""Datapaths.save: layout, formats, the on_same matrix, archiving, atomicity."""

from __future__ import annotations

from pathlib import Path

import pytest

from datapaths.exceptions import ArtifactError

pd = pytest.importorskip("pandas")


def stray_files(directory: Path) -> list[str]:
    """Hidden staging files left behind by an interrupted write."""
    return sorted(p.name for p in directory.rglob("*") if p.name.startswith("."))


class TestFormats:
    def test_parquet_round_trip(self, dp, repo, frame):
        rec = dp.save(frame, name="bazin_train_s01_c01", type="features", fmt="parquet")
        on_disk = repo.roots["features"] / rec["path"]
        assert on_disk.exists()
        pd.testing.assert_frame_equal(pd.read_parquet(on_disk), frame)

    def test_csv_round_trip(self, dp, repo, frame):
        rec = dp.save(frame, name="bazin_train_s01_c01", type="features", fmt="csv")
        assert (repo.roots["features"] / rec["path"]).suffix == ".csv"

    def test_json(self, dp, repo):
        rec = dp.save({"a": 1}, name="cfg", type="misc", fmt="json")
        assert (repo.roots["misc"] / rec["path"]).read_text().strip().startswith("{")

    def test_pickle(self, dp, repo):
        import pickle

        rec = dp.save({"a": 1}, name="obj", type="misc", fmt="pickle")
        path = repo.roots["misc"] / rec["path"]
        assert path.suffix == ".pkl"
        assert pickle.loads(path.read_bytes()) == {"a": 1}

    def test_bin(self, dp, repo):
        rec = dp.save(b"\x00\x01", name="blob", type="misc", fmt="bin")
        assert (repo.roots["misc"] / rec["path"]).read_bytes() == b"\x00\x01"

    def test_bin_rejects_non_bytes(self, dp):
        with pytest.raises(ArtifactError, match="bytes"):
            dp.save("a string", name="blob", type="misc", fmt="bin")

    def test_unsupported_format_raises(self, dp, frame):
        with pytest.raises(ArtifactError, match="Unsupported"):
            dp.save(frame, name="x", type="misc", fmt="zarr")

    def test_tabular_rejects_a_non_dataframe(self, dp):
        with pytest.raises(ArtifactError, match="DataFrame"):
            dp.save({"not": "a frame"}, name="x", type="misc", fmt="parquet")


class TestLayout:
    def test_features_nest_under_their_family(self, dp, frame):
        rec = dp.save(frame, name="bazin_train_s01_c01", type="features")
        assert rec["path"] == str(Path("bazin") / "bazin_train_s01_c01.parquet")

    def test_non_features_are_flat(self, dp):
        rec = dp.save({"a": 1}, name="a_b_c_d", type="misc", fmt="json")
        assert rec["path"] == "a_b_c_d.json"

    def test_force_flat_layout_overrides_family_nesting(self, dp, frame):
        rec = dp.save(frame, name="bazin_train_s01_c01", type="features", force_flat_layout=True)
        assert rec["path"] == "bazin_train_s01_c01.parquet"

    def test_features_name_with_too_few_tokens_is_refused(self, dp, frame):
        with pytest.raises(ArtifactError, match="at least 4"):
            dp.save(frame, name="short_name", type="features")

    def test_explicit_relpath_wins(self, dp, frame):
        rec = dp.save(frame, name="anything", type="features", relpath="custom/here.parquet")
        assert rec["path"] == "custom/here.parquet"

    def test_type_selects_the_root(self, dp, repo):
        rec = dp.save({"a": 1}, name="m", type="models", fmt="json")
        assert rec["root"] == "models"
        assert (repo.roots["models"] / rec["path"]).exists()

    def test_root_key_overrides_the_type_mapping(self, dp, repo):
        rec = dp.save({"a": 1}, name="m", type="models", fmt="json", root_key="misc")
        assert (repo.roots["misc"] / rec["path"]).exists()

    def test_unknown_root_key_raises(self, dp):
        with pytest.raises(ArtifactError, match="not present"):
            dp.save({"a": 1}, name="m", type="misc", fmt="json", root_key="nowhere")


class TestRecord:
    def test_record_fields(self, dp, frame):
        rec = dp.save(
            frame, name="bazin_train_s01_c01", type="features",
            tags=["V02", " bazin "], inputs=["raw_lc"], notes="a note",
        )
        assert rec["type"] == "features"
        assert rec["format"] == "parquet"
        assert rec["hash"].startswith("sha256:")
        assert rec["tags"] == ["bazin", "v02"]
        assert rec["inputs"] == ["raw_lc"]
        assert rec["notes"] == "a note"
        assert rec["updated_by"] == "tester"

    def test_updated_by_can_be_overridden(self, dp, frame):
        rec = dp.save(frame, name="a_b_c_d", type="features", updated_by="pipeline")
        assert rec["updated_by"] == "pipeline"

    def test_record_reaches_the_registry_file(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        assert "a_b_c_d" in repo.read_registry_raw()["artifacts"]

    def test_saved_artifact_is_immediately_resolvable(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        assert dp["a_b_c_d"].exists()


class TestOnSame:
    """Re-saving identical content, by metadata and by hash."""

    def test_skip_warns_and_leaves_the_file_untouched(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        path = repo.roots["features"] / "a" / "a_b_c_d.parquet"
        before = path.stat().st_mtime_ns

        with pytest.warns(UserWarning, match="unchanged"):
            dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])

        assert path.stat().st_mtime_ns == before

    def test_skip_does_not_archive(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        with pytest.warns(UserWarning):
            dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        assert not (repo.roots["features"] / "_archive").exists()

    def test_on_same_overwrite_rewrites(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"], on_same="overwrite")
        assert not (repo.roots["features"] / "_archive").exists()

    def test_on_same_archive_archives_despite_no_change(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"], on_same="archive")
        assert list((repo.roots["features"] / "_archive").rglob("*.parquet"))

    def test_changed_tags_are_not_unchanged(self, dp, repo, frame):
        """Same bytes, different metadata: must write, not skip.

        The skip branch requires the hash AND every metadata field to match.
        Dropping the metadata half would silently discard a re-tagging, which
        is a common reason to re-save an artifact whose contents are final.
        """
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        rec = dp.save(frame, name="a_b_c_d", type="features", tags=["v2"])
        assert rec["tags"] == ["v2"]
        assert dp.get("a_b_c_d", field="tags") == ["v2"]

    @pytest.mark.parametrize(
        "kwargs", [{"notes": "changed"}, {"inputs": ["other"]}, {"tags": ["different"]}]
    )
    def test_any_metadata_change_defeats_the_skip(self, dp, frame, kwargs):
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"], notes="n", inputs=["i"])
        base = {"tags": ["v1"], "notes": "n", "inputs": ["i"]}
        rec = dp.save(frame, name="a_b_c_d", type="features", **{**base, **kwargs})
        for key, value in kwargs.items():
            assert rec[key] == (sorted(value) if key == "tags" else value)


class TestOverwriteAndArchive:
    def test_changed_content_archives_the_previous_file(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        dp.save(frame.assign(flux=frame["flux"] * 2), name="a_b_c_d", type="features")

        archived = list((repo.roots["features"] / "_archive").rglob("*.parquet"))
        assert len(archived) == 1
        assert dp.get("a_b_c_d")["archived"][0]["notes"] == "auto-archived on overwrite"

    def test_archive_previous_false_deletes_instead(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        dp.save(
            frame.assign(flux=1.0), name="a_b_c_d", type="features", archive_previous=False
        )
        assert not (repo.roots["features"] / "_archive").exists()

    def test_archive_list_is_newest_first_and_capped_at_five(self, dp, frame):
        for i in range(8):
            dp.save(frame.assign(flux=float(i)), name="a_b_c_d", type="features")

        archived = dp.get("a_b_c_d")["archived"]
        assert len(archived) == 5
        assert [a["archived_at"] for a in archived] == sorted(
            (a["archived_at"] for a in archived), reverse=True
        )

    def test_overwrite_false_refuses_changed_content(self, dp, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        with pytest.raises(ArtifactError, match="already exists"):
            dp.save(frame.assign(flux=1.0), name="a_b_c_d", type="features", overwrite=False)

    def test_overwrite_false_permits_an_unchanged_rewrite(self, dp, frame):
        """Deliberate: nothing is lost by rewriting identical bytes."""
        dp.save(frame, name="a_b_c_d", type="features", tags=["v1"])
        rec = dp.save(
            frame, name="a_b_c_d", type="features", tags=["v1"],
            overwrite=False, on_same="overwrite",
        )
        assert rec["tags"] == ["v1"]


class TestAtomicity:
    def test_a_failed_write_leaves_no_staging_file(self, dp, repo):
        """Regression guard for a leaked temp file.

        save() stages to `.{name}.{uuid}.new` and write_tabular staged again to
        `.new.tmp`; a serializer that raised part-way left the second file
        behind, and save()'s cleanup only knew about the first. The result was
        hidden partial files accumulating in the data root that nothing ever
        collected.
        """

        class HalfWriter:
            def to_parquet(self, path, index=False):
                Path(path).write_bytes(b"partial")
                raise RuntimeError("disk full")

        with pytest.raises(RuntimeError, match="disk full"):
            dp.save(HalfWriter(), name="a_b_c_d", type="features", fmt="parquet")

        assert stray_files(repo.roots["features"]) == []

    def test_a_failed_write_does_not_register_the_artifact(self, dp, repo):
        class HalfWriter:
            def to_parquet(self, path, index=False):
                Path(path).write_bytes(b"partial")
                raise RuntimeError("disk full")

        with pytest.raises(RuntimeError):
            dp.save(HalfWriter(), name="a_b_c_d", type="features")

        assert dp.get("a_b_c_d") is None

    def test_a_failed_overwrite_leaves_the_previous_file_intact(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        path = repo.roots["features"] / "a" / "a_b_c_d.parquet"
        before = path.read_bytes()

        class HalfWriter:
            def to_parquet(self, path, index=False):
                Path(path).write_bytes(b"partial")
                raise RuntimeError("disk full")

        with pytest.raises(RuntimeError):
            dp.save(HalfWriter(), name="a_b_c_d", type="features")

        assert path.read_bytes() == before
        assert stray_files(repo.roots["features"]) == []

    def test_successful_save_leaves_no_staging_file(self, dp, repo, frame):
        dp.save(frame, name="a_b_c_d", type="features")
        assert stray_files(repo.roots["features"]) == []
