"""Datapaths.register: adopting a file that already exists on disk."""

from __future__ import annotations

import pytest

from datapaths.exceptions import ArtifactError


@pytest.fixture
def outside(tmp_path):
    p = tmp_path / "incoming" / "table.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"pretend parquet")
    return p


@pytest.fixture
def inside(repo):
    p = repo.roots["features"] / "bazin" / "bazin_train_s01_c01.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"pretend parquet")
    return p


class TestInPlace:
    def test_registers_a_file_already_under_a_root(self, dp, inside):
        rec = dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside), fmt="parquet"
        )
        assert rec["path"] == "bazin/bazin_train_s01_c01.parquet"
        assert rec["hash"].startswith("sha256:")
        assert dp["bazin_train_s01_c01"] == inside.resolve()

    def test_path_is_recorded_relative_to_the_root_not_absolute(self, dp, inside):
        rec = dp.register(name="b_t_s_c", type="features", src_path=str(inside), fmt="parquet")
        assert not rec["path"].startswith("/")

    def test_a_file_outside_every_root_is_refused(self, dp, outside):
        with pytest.raises(ArtifactError, match="not under the configured root"):
            dp.register(name="a_b_c_d", type="features", src_path=str(outside), fmt="parquet")

    def test_missing_source_raises(self, dp, tmp_path):
        with pytest.raises(ArtifactError, match="does not exist"):
            dp.register(
                name="a_b_c_d", type="features", src_path=str(tmp_path / "ghost"), fmt="parquet"
            )


class TestCopyIntoCanonical:
    def test_copies_an_outside_file_to_its_canonical_place(self, dp, repo, outside):
        rec = dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(outside),
            fmt="parquet", copy_into_canonical=True,
        )
        dst = repo.roots["features"] / rec["path"]
        assert dst.exists()
        assert dst.read_bytes() == outside.read_bytes()
        assert outside.exists(), "the source is copied, not moved"

    def test_occupied_destination_is_refused_by_default(self, dp, inside, outside):
        with pytest.raises(ArtifactError, match="Destination exists"):
            dp.register(
                name="bazin_train_s01_c01", type="features", src_path=str(outside),
                fmt="parquet", copy_into_canonical=True,
            )

    def test_overwrite_archives_the_previous_file(self, dp, repo, inside, outside):
        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(outside),
            fmt="parquet", copy_into_canonical=True, overwrite=True,
        )
        assert list((repo.roots["features"] / "_archive").rglob("*.parquet"))

    def test_archive_previous_false_deletes_instead(self, dp, repo, inside, outside):
        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(outside),
            fmt="parquet", copy_into_canonical=True, overwrite=True, archive_previous=False,
        )
        assert not (repo.roots["features"] / "_archive").exists()


class TestMetadata:
    def test_tags_are_normalized_like_save(self, dp, inside):
        """register used to store tags verbatim while save lowercased them.

        The registry is a committed file that people read; two entry points
        writing "V02" and "v02" into it made it inconsistent with itself even
        though queries normalize at read time and matched either way.
        """
        rec = dp.register(
            name="b_t_s_c", type="features", src_path=str(inside), fmt="parquet",
            tags=["V02", " Bazin ", "v02"],
        )
        assert rec["tags"] == ["bazin", "v02"]

    def test_matches_what_save_would_have_stored(self, dp, repo, inside, frame):
        dp.save(frame, name="from_save_x_y", type="features", tags=["V02"])
        dp.register(
            name="from_register_x_y", type="features", src_path=str(inside),
            fmt="parquet", tags=["V02"],
        )
        assert dp.get("from_save_x_y")["tags"] == dp.get("from_register_x_y")["tags"]

    def test_notes_inputs_and_updated_by(self, dp, inside):
        rec = dp.register(
            name="b_t_s_c", type="features", src_path=str(inside), fmt="parquet",
            notes="adopted", inputs=["upstream"],
        )
        assert rec["notes"] == "adopted"
        assert rec["inputs"] == ["upstream"]
        assert rec["updated_by"] == "tester"

    def test_re_registering_replaces_the_record(self, dp, inside):
        dp.register(name="b_t_s_c", type="features", src_path=str(inside),
                    fmt="parquet", tags=["old"])
        dp.register(name="b_t_s_c", type="features", src_path=str(inside),
                    fmt="parquet", tags=["new"])
        assert dp.get("b_t_s_c")["tags"] == ["new"]
