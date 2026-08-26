"""Roots that are harder to tell apart than their names suggest.

Three advisories, none of which refuses a file: a roots file that is merely
unusual should still load. Only the same-directory case is a correctness
matter -- the others are about a lookup failing on a typo.
"""

from __future__ import annotations

import pytest

from datapaths.exceptions import ConfigWarning


def config_warnings(recwarn):
    return [w for w in recwarn if issubclass(w.category, ConfigWarning)]


class TestKeyCaseCollisions:
    def test_names_differing_only_in_case_warn(self, repo, tmp_path):
        a, b = tmp_path / "one", tmp_path / "two"
        a.mkdir()
        b.mkdir()
        repo.write_roots({"features": a, "FEATURES": b})
        with pytest.warns(ConfigWarning, match="differing only in case"):
            repo.dp()

    def test_the_warning_names_both(self, repo, tmp_path):
        a, b = tmp_path / "one", tmp_path / "two"
        a.mkdir()
        b.mkdir()
        repo.write_roots({"features": a, "FEATURES": b})
        with pytest.warns(ConfigWarning, match="'FEATURES', 'features'"):
            repo.dp()

    def test_both_roots_still_load_and_stay_distinct(self, repo, tmp_path):
        a, b = tmp_path / "one", tmp_path / "two"
        a.mkdir()
        b.mkdir()
        repo.write_roots({"features": a, "FEATURES": b})
        with pytest.warns(ConfigWarning):
            dp = repo.dp()
        assert dp["features"] == a
        assert dp["FEATURES"] == b

    def test_ordinary_names_do_not_warn(self, repo, recwarn):
        repo.dp()
        assert config_warnings(recwarn) == []

    def test_names_differing_by_more_than_case_do_not_warn(self, repo, tmp_path, recwarn):
        d = tmp_path / "plots"
        d.mkdir()
        repo.write_roots({**repo.roots, "plots": d})
        repo.dp()
        assert config_warnings(recwarn) == []


class TestSameDirectory:
    def test_two_names_for_one_path_warn(self, repo, tmp_path):
        shared = tmp_path / "shared"
        shared.mkdir()
        repo.write_roots({"features": shared, "plots": shared})
        with pytest.warns(ConfigWarning, match="are the same directory"):
            repo.dp()

    def test_the_warning_explains_the_consequence(self, repo, tmp_path):
        shared = tmp_path / "shared"
        shared.mkdir()
        repo.write_roots({"features": shared, "plots": shared})
        with pytest.warns(ConfigWarning, match="overwrite each other"):
            repo.dp()

    def test_a_symlinked_root_is_caught_too(self, repo, tmp_path):
        """samefile settles it whatever the cause, not just an identical string."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not permitted on this platform")
        repo.write_roots({"features": real, "plots": link})
        with pytest.warns(ConfigWarning, match="same directory"):
            repo.dp()

    def test_distinct_directories_do_not_warn(self, repo, recwarn):
        repo.dp()
        assert config_warnings(recwarn) == []

    def test_paths_differing_only_in_case_that_both_exist_are_proven_distinct(
        self, repo, tmp_path, recwarn
    ):
        """On a case-sensitive filesystem these are two directories, and
        samefile says so -- no warning is warranted."""
        lower, upper = tmp_path / "data", tmp_path / "DATA"
        lower.mkdir()
        # exist_ok, because on a case-insensitive filesystem this IS lower --
        # a plain mkdir would raise FileExistsError before samefile could say so.
        upper.mkdir(exist_ok=True)
        if lower.samefile(upper):
            pytest.skip("case-insensitive filesystem: they are one directory")
        repo.write_roots({"a_root": lower, "b_root": upper})
        repo.dp()
        assert config_warnings(recwarn) == []

    def test_paths_differing_only_in_case_that_do_not_exist_warn(self, repo, tmp_path):
        """Nothing on disk can settle it, so say what the risk is.

        Which of the two warnings fires is platform-dependent and both are
        right: on Windows, Path comparison is case-insensitive, so these are
        equal and the stronger "same directory" warning is the accurate one.
        What must hold everywhere is that the pair is flagged at all.
        """
        repo.write_roots({"a_root": tmp_path / "ghost", "b_root": tmp_path / "GHOST"})
        with pytest.warns(ConfigWarning, match="Roots 'a_root' and 'b_root'") as record:
            repo.dp()
        message = str(record[0].message)
        assert "same directory" in message or "differing only" in message


class TestLookupHint:
    def test_wrong_case_on_a_root_suggests_the_right_one(self, dp):
        with pytest.raises(KeyError, match="did you mean 'features'"):
            dp["FEATURES"]

    def test_wrong_case_on_a_root_prefix_suggests_too(self, dp):
        with pytest.raises(KeyError, match="did you mean 'features'"):
            dp["root_Features"]

    def test_wrong_case_on_an_artifact_name_suggests_it(self, repo, frame):
        dp = repo.dp()
        dp.save(frame, name="bazin_train_s01_c01", type="features")
        with pytest.raises(KeyError, match="did you mean 'bazin_train_s01_c01'"):
            dp["BAZIN_train_s01_c01"]

    def test_the_hint_says_matching_is_case_sensitive(self, dp):
        with pytest.raises(KeyError, match="case-sensitive"):
            dp["Features"]

    def test_a_genuinely_absent_key_gets_no_invented_suggestion(self, dp):
        with pytest.raises(KeyError) as exc:
            dp["no_such_thing"]
        assert "did you mean" not in str(exc.value)

    def test_a_root_prefix_does_not_suggest_an_artifact(self, repo, frame):
        """root_<x> asks for a root; suggesting an artifact would mislead."""
        dp = repo.dp()
        dp.save(frame, name="bazin_train_s01_c01", type="features")
        with pytest.raises(KeyError) as exc:
            dp["root_BAZIN_train_s01_c01"]
        assert "did you mean" not in str(exc.value)
