"""Datapaths.verify: the four statuses, and the filters that select rows.

verify is the function the whole registry exists to support -- it is what
catches an artifact regenerated without being re-registered -- so each status
gets an artifact of its own rather than sharing a fixture.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")


@pytest.fixture
def four_states(repo, frame):
    """One artifact per verify status, plus the roots edit that orphans one."""
    dp = repo.dp()
    dp.save(frame, name="ok_a_b_c", type="features", tags=["keep"])
    dp.save(frame, name="missing_a_b_c", type="features", tags=["keep"])
    dp.save(frame, name="drifted_a_b_c", type="features", tags=["other"])
    dp.save({"x": 1}, name="orphan", type="models", fmt="json")

    (repo.roots["features"] / "missing" / "missing_a_b_c.parquet").unlink()
    (repo.roots["features"] / "drifted" / "drifted_a_b_c.parquet").write_bytes(b"rewritten")

    roots = dict(repo.roots)
    del roots["models"]
    repo.write_roots(roots)

    return repo.dp()


def status_of(rows, name):
    return next(r["status"] for r in rows if r["name"] == name)


class TestStatuses:
    def test_ok(self, four_states):
        assert status_of(four_states.verify(), "ok_a_b_c") == "OK"

    def test_missing_file(self, four_states):
        assert status_of(four_states.verify(), "missing_a_b_c") == "MISSING"

    def test_hash_mismatch(self, four_states):
        assert status_of(four_states.verify(), "drifted_a_b_c") == "HASH_MISMATCH"

    def test_root_missing_from_the_roots_file(self, four_states):
        assert status_of(four_states.verify(), "orphan") == "ROOT_MISSING"

    def test_mismatch_reports_both_hashes(self, four_states):
        row = next(r for r in four_states.verify() if r["name"] == "drifted_a_b_c")
        assert row["expected"] != row["actual"]
        assert row["actual"].startswith("sha256:")

    def test_every_artifact_is_reported(self, four_states):
        assert len(four_states.verify()) == 4

    def test_content_rewritten_to_identical_bytes_is_ok(self, repo, frame):
        """Only the hash matters, not the mtime -- a rerun that reproduces the
        same bytes is not drift."""
        dp = repo.dp()
        dp.save(frame, name="a_b_c_d", type="features")
        path = repo.roots["features"] / "a" / "a_b_c_d.parquet"
        path.write_bytes(path.read_bytes())
        assert status_of(dp.verify(), "a_b_c_d") == "OK"


class TestFilters:
    def test_names_filter(self, four_states):
        rows = four_states.verify(names=["ok_a_b_c", "drifted_a_b_c"])
        assert {r["name"] for r in rows} == {"ok_a_b_c", "drifted_a_b_c"}

    def test_type_filter(self, four_states):
        rows = four_states.verify(type="models")
        assert [r["name"] for r in rows] == ["orphan"]

    def test_tag_filter(self, four_states):
        rows = four_states.verify(tag="keep")
        assert {r["name"] for r in rows} == {"ok_a_b_c", "missing_a_b_c"}

    def test_tag_filter_is_case_insensitive(self, four_states):
        assert len(four_states.verify(tag="KEEP")) == 2

    def test_filters_compose(self, four_states):
        rows = four_states.verify(names=["ok_a_b_c", "missing_a_b_c"], tag="keep", type="features")
        assert len(rows) == 2

    def test_unknown_name_yields_nothing(self, four_states):
        assert four_states.verify(names=["nope"]) == []


class TestTagQueryForms:
    """verify accepts the same tag forms as list, so the CLI's --tag agrees."""

    def test_comma_string_filters_on_every_tag(self, repo, frame):
        dp = repo.dp()
        dp.save(frame, name="both_a_b_c", type="features", tags=["v02", "bazin"])
        dp.save(frame.assign(flux=1.0), name="one_a_b_c", type="features", tags=["v02"])
        rows = dp.verify(tag="v02,bazin")
        assert [r["name"] for r in rows] == ["both_a_b_c"]

    def test_list_form_works_too(self, repo, frame):
        dp = repo.dp()
        dp.save(frame, name="both_a_b_c", type="features", tags=["v02", "bazin"])
        assert len(dp.verify(tag=["v02", "bazin"])) == 1
