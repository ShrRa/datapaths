"""Registering files this package has no saver for.

The registry tracks a path, a hash and metadata; none of that needs the
ability to serialize the format. A FITS cube, an HDF5 model or a PDF is a
perfectly good thing to record, and only save() genuinely needs a closed
format vocabulary.
"""

from __future__ import annotations

import pytest

from datapaths.artifacts import canonical_relpath
from datapaths.exceptions import ArtifactError, ArtifactWarning


@pytest.fixture
def fits_in_root(repo):
    p = repo.roots["misc"] / "cubes" / "image.fits"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"SIMPLE  =  T")
    return p


@pytest.fixture
def fits_outside(tmp_path):
    p = tmp_path / "incoming" / "image.fits"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"SIMPLE  =  T")
    return p


class TestInPlaceTakesAnyFormat:
    def test_a_format_with_no_saver_registers(self, dp, fits_in_root):
        rec = dp.register(name="cube", type="misc", src_path=str(fits_in_root), fmt="fits")
        assert rec["format"] == "fits"
        assert rec["path"] == "cubes/image.fits"

    def test_it_resolves_and_verifies(self, dp, fits_in_root):
        dp.register(name="cube", type="misc", src_path=str(fits_in_root), fmt="fits")
        assert dp["cube"] == fits_in_root.resolve()
        assert [r["status"] for r in dp.verify(names=["cube"])] == ["OK"]

    def test_drift_is_detected_like_any_other_artifact(self, dp, fits_in_root):
        dp.register(name="cube", type="misc", src_path=str(fits_in_root), fmt="fits")
        fits_in_root.write_bytes(b"TAMPERED")
        assert [r["status"] for r in dp.verify(names=["cube"])] == ["HASH_MISMATCH"]

    @pytest.mark.parametrize("fmt", ["fits", "hdf5", "pdf", "npz", "anything"])
    def test_no_format_is_rejected_in_place(self, dp, fits_in_root, fmt):
        rec = dp.register(name=f"a_{fmt}", type="misc", src_path=str(fits_in_root), fmt=fmt)
        assert rec["format"] == fmt

    def test_a_file_without_a_suffix_is_fine_in_place(self, dp, repo):
        """No extension is needed: the path is the file's own location."""
        p = repo.roots["misc"] / "NOEXTENSION"
        p.write_bytes(b"x")
        rec = dp.register(name="noext", type="misc", src_path=str(p), fmt="fits")
        assert rec["path"] == "NOEXTENSION"


class TestCopyBorrowsTheSourceSuffix:
    def test_canonical_name_keeps_the_source_extension(self, dp, repo, fits_outside):
        rec = dp.register(
            name="cube", type="misc", src_path=str(fits_outside),
            fmt="fits", copy_into_canonical=True,
        )
        assert rec["path"] == "cube.fits"
        assert (repo.roots["misc"] / "cube.fits").exists()

    def test_a_known_format_still_uses_the_mapping_not_the_suffix(self, dp, repo, tmp_path):
        """A .pickle source registered as fmt=pickle canonicalizes to .pkl."""
        src = tmp_path / "obj.pickle"
        src.write_bytes(b"x")
        rec = dp.register(
            name="obj", type="misc", src_path=str(src), fmt="pickle", copy_into_canonical=True
        )
        assert rec["path"] == "obj.pkl"

    def test_explicit_relpath_still_wins_when_copying(self, dp, repo, fits_outside):
        rec = dp.register(
            name="cube", type="misc", src_path=str(fits_outside), fmt="fits",
            relpath="cubes/panel_a.fits", copy_into_canonical=True,
        )
        assert rec["path"] == "cubes/panel_a.fits"
        assert (repo.roots["misc"] / "cubes" / "panel_a.fits").exists()

    def test_an_unknown_format_with_no_suffix_is_refused_when_copying(self, dp, tmp_path):
        """Nothing can name the destination file, so say so rather than guess."""
        src = tmp_path / "NOEXTENSION"
        src.write_bytes(b"x")
        with pytest.raises(ArtifactError, match="Unsupported format: fits"):
            dp.register(
                name="cube", type="misc", src_path=str(src),
                fmt="fits", copy_into_canonical=True,
            )

    def test_that_error_points_at_the_ways_out(self, dp, tmp_path):
        src = tmp_path / "NOEXTENSION"
        src.write_bytes(b"x")
        with pytest.raises(ArtifactError, match="relpath"):
            dp.register(
                name="cube", type="misc", src_path=str(src),
                fmt="fits", copy_into_canonical=True,
            )


class TestSaveStaysClosed:
    """save() has to serialize, so its vocabulary genuinely is closed."""

    @pytest.mark.parametrize("fmt", ["fits", "hdf5", "npz"])
    def test_save_still_refuses_a_format_it_cannot_write(self, dp, fmt):
        with pytest.raises(ArtifactError, match="Unsupported format"):
            dp.save(b"x", name="cube", type="misc", fmt=fmt)

    def test_the_message_names_what_it_can_write(self, dp):
        with pytest.raises(ArtifactError, match="bin, csv, json, parquet, pickle"):
            dp.save(b"x", name="cube", type="misc", fmt="fits")


class TestIgnoredRelpathIsAudible:
    def test_relpath_in_place_warns(self, dp, fits_in_root):
        with pytest.warns(ArtifactWarning, match="ignored when registering in place"):
            dp.register(
                name="cube", type="misc", src_path=str(fits_in_root),
                fmt="fits", relpath="somewhere/else.fits",
            )

    def test_the_warning_names_the_way_to_get_what_was_asked(self, dp, fits_in_root):
        with pytest.warns(ArtifactWarning, match="copy_into_canonical=True"):
            dp.register(
                name="cube", type="misc", src_path=str(fits_in_root),
                fmt="fits", relpath="somewhere/else.fits",
            )

    def test_the_record_still_uses_the_files_own_location(self, dp, fits_in_root):
        with pytest.warns(ArtifactWarning):
            rec = dp.register(
                name="cube", type="misc", src_path=str(fits_in_root),
                fmt="fits", relpath="somewhere/else.fits",
            )
        assert rec["path"] == "cubes/image.fits"

    def test_no_warning_without_relpath(self, dp, fits_in_root, recwarn):
        dp.register(name="cube", type="misc", src_path=str(fits_in_root), fmt="fits")
        assert [w for w in recwarn if issubclass(w.category, ArtifactWarning)] == []

    def test_no_warning_when_copying(self, dp, fits_outside, recwarn):
        dp.register(
            name="cube", type="misc", src_path=str(fits_outside), fmt="fits",
            relpath="cubes/panel.fits", copy_into_canonical=True,
        )
        assert [w for w in recwarn if issubclass(w.category, ArtifactWarning)] == []


class TestCanonicalRelpathFallback:
    def test_fallback_ext_is_used_only_for_unknown_formats(self):
        assert canonical_relpath("x", "fits", fallback_ext=".fits") == \
            __import__("pathlib").Path("x.fits")
        assert canonical_relpath("x", "pickle", fallback_ext=".pickle") == \
            __import__("pathlib").Path("x.pkl")

    def test_a_bare_suffix_without_the_dot_works_too(self):
        assert canonical_relpath("x", "fits", fallback_ext="fits").suffix == ".fits"

    def test_no_fallback_and_unknown_format_raises(self):
        with pytest.raises(ArtifactError, match="Unsupported format"):
            canonical_relpath("x", "fits")
