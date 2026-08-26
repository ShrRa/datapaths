"""Pure helpers: path construction, tag normalization, hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from datapaths.artifacts import archive_path, canonical_relpath, normalize_tag, normalize_tags
from datapaths.exceptions import ArtifactError
from datapaths.hashing import BUF, sha256_bytes, sha256_file, short_hash


class TestCanonicalRelpath:
    @pytest.mark.parametrize(
        "fmt,ext",
        [("parquet", "parquet"), ("csv", "csv"), ("json", "json"), ("bin", "bin"), ("pickle", "pkl")],
    )
    def test_extension_per_format(self, fmt, ext):
        got = canonical_relpath("a_b_c_d", fmt, layout="flat")
        assert got == Path(f"a_b_c_d.{ext}")

    def test_pickle_is_abbreviated_to_pkl(self):
        assert canonical_relpath("x", "pickle", layout="flat").suffix == ".pkl"

    def test_one_level_family_nests_under_the_first_token(self):
        got = canonical_relpath("bazin_train_s01_c01", "parquet")
        assert got == Path("bazin") / "bazin_train_s01_c01.parquet"

    def test_flat_layout_does_not_nest(self):
        got = canonical_relpath("bazin_train_s01_c01", "parquet", layout="flat")
        assert got.parent == Path(".")

    def test_family_naming_refuses_too_few_tokens(self):
        with pytest.raises(ArtifactError, match="at least 4"):
            canonical_relpath("only_three_parts", "parquet", enforce_family_naming=True)

    def test_family_naming_accepts_exactly_four(self):
        assert canonical_relpath("a_b_c_d", "parquet", enforce_family_naming=True).parent == Path("a")

    def test_unenforced_short_name_still_gets_a_family(self):
        assert canonical_relpath("solo", "json") == Path("solo") / "solo.json"

    def test_unsupported_format_raises(self):
        with pytest.raises(ArtifactError, match="Unsupported format"):
            canonical_relpath("x", "zarr", layout="flat")

    def test_unknown_layout_raises(self):
        with pytest.raises(ArtifactError, match="Unknown layout"):
            canonical_relpath("x", "json", layout="pyramid")


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
