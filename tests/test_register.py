"""Datapaths.register: adopting a file that already exists on disk."""

from __future__ import annotations

import pytest

from datapaths.exceptions import ArtifactError, ArtifactWarning


@pytest.fixture
def outside(tmp_path):
    p = tmp_path / "incoming" / "table.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"pretend parquet")
    return p


@pytest.fixture
def inside(repo):
    """A file under a root, in a subdirectory of its own.

    Deliberately nested: registering in place adopts a file exactly where it
    lies, so an existing layout must survive even though nothing *builds*
    nested paths any more.
    """
    p = repo.roots["features"] / "bazin" / "bazin_train_s01_c01.parquet"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"pretend parquet")
    return p


@pytest.fixture
def occupying_canonical(repo):
    """A file already sitting where copy_into_canonical would put one."""
    p = repo.roots["features"] / "bazin_train_s01_c01.parquet"
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
        with pytest.raises(ArtifactError, match="not under the 'features' root"):
            dp.register(name="a_b_c_d", type="features", src_path=str(outside), fmt="parquet")

    def test_that_error_names_the_file_and_the_way_out(self, dp, outside):
        with pytest.raises(ArtifactError, match="copy_into_canonical=True") as exc:
            dp.register(name="a_b_c_d", type="features", src_path=str(outside), fmt="parquet")
        assert str(outside) in str(exc.value)

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

    def test_occupied_destination_is_refused_by_default(self, dp, occupying_canonical, outside):
        with pytest.raises(ArtifactError, match="Destination exists"):
            dp.register(
                name="bazin_train_s01_c01", type="features", src_path=str(outside),
                fmt="parquet", copy_into_canonical=True,
            )

    def test_overwrite_archives_the_previous_file(self, dp, repo, occupying_canonical, outside):
        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(outside),
            fmt="parquet", copy_into_canonical=True, overwrite_file=True,
        )
        assert list((repo.roots["features"] / "_archive").rglob("*.parquet"))

    def test_archive_previous_false_deletes_instead(self, dp, repo, occupying_canonical, outside):
        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(outside),
            fmt="parquet", copy_into_canonical=True, overwrite_file=True, archive_previous=False,
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

    def test_re_registering_replaces_the_record_when_asked(self, dp, inside):
        """Replacing is now opt-in; see TestOverwriteHistory for the default."""
        dp.register(name="b_t_s_c", type="features", src_path=str(inside),
                    fmt="parquet", tags=["old"])
        dp.register(name="b_t_s_c", type="features", src_path=str(inside),
                    fmt="parquet", tags=["new"], overwrite_history=True)
        assert dp.get("b_t_s_c")["tags"] == ["new"]


class TestOverwriteHistory:
    """Re-registering a known name must not silently discard its record.

    register used to replace the registry entry wholesale, so a re-register
    dropped the artifact's archived history -- the one thing that cannot be
    reconstructed from the files on disk.
    """

    def test_a_known_name_is_skipped_with_a_warning(self, dp, inside, outside):
        first = dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside), fmt="parquet"
        )
        with pytest.warns(ArtifactWarning, match="already registered"):
            again = dp.register(
                name="bazin_train_s01_c01", type="features", src_path=str(inside),
                fmt="parquet", notes="second attempt",
            )
        assert again["notes"] == first["notes"] != "second attempt"

    def test_the_warning_names_the_way_through(self, dp, inside):
        dp.register(name="bazin_train_s01_c01", type="features", src_path=str(inside), fmt="parquet")
        with pytest.warns(ArtifactWarning, match="overwrite_history=True"):
            dp.register(
                name="bazin_train_s01_c01", type="features", src_path=str(inside), fmt="parquet"
            )

    def test_the_registry_is_untouched_by_a_skipped_register(self, dp, inside):
        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside),
            fmt="parquet", notes="original",
        )
        before = dp.cfg.registry_file.read_text()
        with pytest.warns(ArtifactWarning):
            dp.register(
                name="bazin_train_s01_c01", type="features", src_path=str(inside),
                fmt="parquet", notes="clobbered",
            )
        assert dp.cfg.registry_file.read_text() == before

    def test_overwrite_history_true_rewrites_the_record(self, dp, inside):
        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside),
            fmt="parquet", notes="original",
        )
        rec = dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside),
            fmt="parquet", notes="deliberate", overwrite_history=True,
        )
        assert rec["notes"] == "deliberate"
        assert dp.get("bazin_train_s01_c01", field="notes") == "deliberate"

    def test_overwrite_history_preserves_the_archived_list(self, dp, repo, frame, inside):
        """The archive is provenance: a rewrite updates the record, not the history."""
        dp.save(frame, name="bazin_train_s01_c01", type="features")
        dp.save(frame.assign(flux=1.0), name="bazin_train_s01_c01", type="features")
        archived = dp.get("bazin_train_s01_c01")["archived"]
        assert archived

        dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside),
            fmt="parquet", overwrite_history=True,
        )
        assert dp.get("bazin_train_s01_c01")["archived"] == archived

    def test_an_unknown_name_needs_no_flag(self, dp, inside):
        rec = dp.register(
            name="bazin_train_s01_c01", type="features", src_path=str(inside), fmt="parquet"
        )
        assert rec["notes"] == ""


class TestNameValidation:
    @pytest.mark.parametrize("name", ["../escape", "sub/dir", ".hidden", ""])
    def test_a_bad_name_is_refused(self, dp, inside, name):
        with pytest.raises(ArtifactError):
            dp.register(name=name, type="features", src_path=str(inside), fmt="parquet")

    def test_nothing_is_registered_when_the_name_is_refused(self, dp, inside):
        with pytest.raises(ArtifactError):
            dp.register(name="../escape", type="features", src_path=str(inside), fmt="parquet")
        assert dp.list() == []

    def test_a_relpath_escaping_the_root_is_refused(self, dp, outside):
        with pytest.raises(ArtifactError, match="outside"):
            dp.register(
                name="cube", type="features", src_path=str(outside), fmt="parquet",
                relpath="../../escaped.parquet", copy_into_canonical=True,
            )
