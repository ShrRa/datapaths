"""Pure helpers: path construction, tag normalization, hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from datapaths.artifacts import (
    archive_path,
    canonical_relpath,
    normalize_tag,
    normalize_tags,
    validate_artifact_name,
    validate_relpath,
)
from datapaths.exceptions import ArtifactError
from datapaths.hashing import BUF, sha256_bytes, sha256_file, short_hash


class TestCanonicalRelpath:
    @pytest.mark.parametrize(
        "fmt,ext",
        [("parquet", "parquet"), ("csv", "csv"), ("json", "json"), ("bin", "bin"), ("pickle", "pkl")],
    )
    def test_extension_per_format(self, fmt, ext):
        got = canonical_relpath("a_b_c_d", fmt)
        assert got == Path(f"a_b_c_d.{ext}")

    def test_pickle_is_abbreviated_to_pkl(self):
        assert canonical_relpath("x", "pickle").suffix == ".pkl"

    def test_the_layout_is_always_flat(self):
        """One rule for every type: {name}.{ext}, directly under the root.

        Nesting used to depend on the artifact's type, which made `type` mean
        two things at once -- which root, and what shape the path takes inside
        it. It now means only the first.
        """
        assert canonical_relpath("bazin_train_s01_c01", "parquet").parent == Path(".")

    @pytest.mark.parametrize("name", ["solo", "two_parts", "a_b_c", "a_b_c_d", "a_b_c_d_e"])
    def test_no_name_shape_is_required(self, name):
        """Underscore count carries no meaning. It once had to be at least 4."""
        assert canonical_relpath(name, "json") == Path(f"{name}.json")

    def test_unsupported_format_raises(self):
        with pytest.raises(ArtifactError, match="Unsupported format"):
            canonical_relpath("x", "zarr")


class TestValidateArtifactName:
    """What replaces the old naming convention.

    The package used to refuse a features name with too few underscores while
    happily accepting one that escaped the root. This is the check that
    actually matters: a name becomes a filename, so it must stay one path
    component and it must not be able to point outside its root.
    """

    @pytest.mark.parametrize(
        "name",
        ["solo", "two_parts", "a_b_c_d", "lc-cube", "cube.v2", "Features_Train", "café", "x" * 200],
    )
    def test_ordinary_names_pass_through(self, name):
        assert validate_artifact_name(name) == name

    @pytest.mark.parametrize("name", ["", "   ", "\t"])
    def test_empty_or_blank_is_refused(self, name):
        with pytest.raises(ArtifactError, match="empty"):
            validate_artifact_name(name)

    @pytest.mark.parametrize("name", ["sub/dir", "sub\\dir", "a/b/c"])
    def test_a_separator_is_refused(self, name):
        """A name is one path component. Use relpath to nest deliberately."""
        with pytest.raises(ArtifactError, match="separator"):
            validate_artifact_name(name)

    @pytest.mark.parametrize("name", ["..", ".", "../escape", "../../escape"])
    def test_traversal_is_refused(self, name):
        with pytest.raises(ArtifactError):
            validate_artifact_name(name)

    @pytest.mark.parametrize("name", [".hidden", ".datapaths"])
    def test_a_leading_dot_is_refused(self, name):
        """Hidden files have no place in a provenance registry."""
        with pytest.raises(ArtifactError, match="dot"):
            validate_artifact_name(name)

    def test_a_leading_tilde_is_refused(self):
        with pytest.raises(ArtifactError):
            validate_artifact_name("~cache")

    @pytest.mark.parametrize("name", ["nul\x00byte", "bell\x07", "line\nbreak"])
    def test_control_characters_are_refused(self, name):
        with pytest.raises(ArtifactError, match="control"):
            validate_artifact_name(name)

    def test_an_absolute_path_is_refused(self):
        with pytest.raises(ArtifactError):
            validate_artifact_name("/etc/passwd")

    def test_the_error_names_the_offending_value(self):
        with pytest.raises(ArtifactError) as exc:
            validate_artifact_name("../escape")
        assert "../escape" in str(exc.value)


class TestValidateRelpath:
    def test_an_ordinary_relative_path_passes(self):
        assert validate_relpath("cubes/panel_a.fits") == Path("cubes/panel_a.fits")

    @pytest.mark.parametrize("rel", ["../outside.fits", "cubes/../../outside.fits", ".."])
    def test_traversal_is_refused(self, rel):
        with pytest.raises(ArtifactError, match="outside"):
            validate_relpath(rel)

    def test_an_absolute_path_is_refused(self, tmp_path):
        with pytest.raises(ArtifactError, match="relative"):
            validate_relpath(str(tmp_path / "x.fits"))

    def test_an_empty_relpath_is_refused(self):
        with pytest.raises(ArtifactError):
            validate_relpath("")


class TestArchivePath:
    def test_carries_timestamp_and_short_hash_under_archive(self, tmp_path):
        got = archive_path(tmp_path, Path("bazin/f.parquet"), "sha256:" + "ab" * 32)
        assert got.parent == tmp_path / "_archive" / "bazin"
        assert got.suffix == ".parquet"
        assert got.stem.startswith("f__")
        assert got.stem.endswith("__" + "ab" * 5)

    def test_two_archives_of_one_file_do_not_collide_on_hash(self, tmp_path):
        a = archive_path(tmp_path, Path("f.json"), "sha256:" + "aa" * 32)
        b = archive_path(tmp_path, Path("f.json"), "sha256:" + "bb" * 32)
        assert a != b


class TestNormalizeTags:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, set()),
            ([], set()),
            ("", set()),
            ("v02", {"v02"}),
            ("  V02  ", {"v02"}),
            ("a,b,c", {"a", "b", "c"}),
            ("a, B ,a", {"a", "b"}),
            (["A", "a", " a "], {"a"}),
            (("x", "Y"), {"x", "y"}),
            ({"m", "N"}, {"m", "n"}),
            (42, {"42"}),
        ],
    )
    def test_normalization(self, raw, expected):
        assert normalize_tags(raw) == expected

    def test_single_tag_is_lowercased_and_stripped(self):
        assert normalize_tag("  Bazin ") == "bazin"


class TestHashing:
    def test_file_and_bytes_agree(self, tmp_path):
        p = tmp_path / "f.bin"
        data = b"some content"
        p.write_bytes(data)
        assert sha256_file(p) == sha256_bytes(data)

    def test_prefixed_with_the_algorithm(self, tmp_path):
        p = tmp_path / "f.bin"
        p.write_bytes(b"x")
        h = sha256_file(p)
        assert h.startswith("sha256:")
        assert h.split(":", 1)[1] == hashlib.sha256(b"x").hexdigest()

    def test_chunking_is_correct_across_the_buffer_boundary(self, tmp_path):
        """Content larger than one read() must hash as a whole, not per chunk."""
        data = b"\xa5" * (BUF * 2 + 7)
        p = tmp_path / "big.bin"
        p.write_bytes(data)
        assert sha256_file(p) == sha256_bytes(data)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        assert sha256_file(p) == sha256_bytes(b"")

    def test_short_hash_strips_the_prefix(self):
        assert short_hash("sha256:" + "ab" * 32) == "ab" * 5

    def test_short_hash_tolerates_a_bare_digest(self):
        assert short_hash("cd" * 32) == "cd" * 5

    def test_short_hash_length_is_configurable(self):
        assert len(short_hash("sha256:" + "ef" * 32, n=6)) == 6
