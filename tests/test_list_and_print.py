"""Datapaths.list filtering and print_paths rendering."""

from __future__ import annotations

import pytest


@pytest.fixture
def catalogue(repo):
    repo.write_registry(
        {
            "bazin_train_s01_c01": {
                "type": "features", "root": "features", "format": "parquet",
                "path": "bazin/bazin_train_s01_c01.parquet",
                "tags": ["v02", "bazin"], "notes": "event window refit",
                "updated_at": "2026-03-01T00:00:00+00:00",
            },
            "potica_train_s01_c01": {
                "type": "features", "root": "features", "format": "parquet",
                "path": "potica/potica_train_s01_c01.parquet",
                "tags": ["v02"], "notes": "shape ceilings",
                "updated_at": "2026-05-01T00:00:00+00:00",
            },
            "lgbm_model": {
                "type": "models", "root": "models", "format": "pickle",
                "path": "lgbm_model.pkl", "tags": ["V01"], "notes": "",
                "updated_at": "2026-01-01T00:00:00+00:00",
            },
        }
    )
    return repo.dp()


def names(rows):
    return [r["name"] for r in rows]


class TestList:
    def test_unfiltered_returns_everything(self, catalogue):
        assert len(catalogue.list()) == 3

    def test_sorted_by_updated_at_descending(self, catalogue):
        assert names(catalogue.list()) == [
            "potica_train_s01_c01", "bazin_train_s01_c01", "lgbm_model"
        ]

    def test_name_filter_is_a_substring_match(self, catalogue):
        assert names(catalogue.list(name="potica")) == ["potica_train_s01_c01"]

    def test_name_filter_is_case_insensitive(self, catalogue):
        assert names(catalogue.list(name="POTICA")) == ["potica_train_s01_c01"]

    def test_type_filter_is_exact(self, catalogue):
        assert names(catalogue.list(type="models")) == ["lgbm_model"]

    def test_single_tag(self, catalogue):
        assert len(catalogue.list(tag="v02")) == 2

    def test_tag_matching_is_case_insensitive_on_both_sides(self, catalogue):
        assert names(catalogue.list(tag="v01")) == ["lgbm_model"]
        assert names(catalogue.list(tag="V01")) == ["lgbm_model"]

    def test_multiple_tags_are_and_not_or(self, catalogue):
        """A record must carry every requested tag, not any of them."""
        assert names(catalogue.list(tag=["v02", "bazin"])) == ["bazin_train_s01_c01"]

    def test_comma_separated_tags_behave_the_same(self, catalogue):
        assert names(catalogue.list(tag="v02,bazin")) == ["bazin_train_s01_c01"]

    def test_text_searches_notes(self, catalogue):
        assert names(catalogue.list(text="ceilings")) == ["potica_train_s01_c01"]

    def test_text_searches_the_name_too(self, catalogue):
        assert names(catalogue.list(text="lgbm")) == ["lgbm_model"]

    def test_filters_compose(self, catalogue):
        assert catalogue.list(type="features", tag="v02", text="refit") == \
            catalogue.list(name="bazin")

    def test_no_match_is_an_empty_list(self, catalogue):
        assert catalogue.list(name="nonexistent") == []

    def test_rows_carry_the_name_alongside_the_record(self, catalogue):
        row = catalogue.list(name="lgbm")[0]
        assert row["name"] == "lgbm_model"
        assert row["format"] == "pickle"


class TestPrintPaths:
    def test_renders_absolute_paths(self, catalogue, repo, capsys):
        catalogue.print_paths(name="lgbm")
        out = capsys.readouterr().out
        assert str(repo.roots["models"] / "lgbm_model.pkl") in out

    def test_header_and_rule(self, catalogue, capsys):
        catalogue.print_paths()
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].startswith("name")
        assert set(lines[1]) <= {"-", "+", " "}
        assert len(lines) == 2 + 3

    def test_updated_at_alias_is_accepted_with_a_space(self, catalogue, capsys):
        catalogue.print_paths(columns=["name", "updated at"], name="lgbm")
        assert "2026-01-01" in capsys.readouterr().out

    def test_custom_columns_are_respected(self, catalogue, capsys):
        catalogue.print_paths(columns=["name", "format"], name="lgbm")
        out = capsys.readouterr().out
        assert "pickle" in out
        assert "lgbm_model.pkl" not in out

    def test_tags_are_rendered_as_a_comma_list(self, catalogue, capsys):
        catalogue.print_paths(columns=["name", "tags"], name="bazin")
        assert "v02,bazin" in capsys.readouterr().out

    def test_filters_reach_the_output(self, catalogue, capsys):
        catalogue.print_paths(type="models")
        out = capsys.readouterr().out
        assert "lgbm_model" in out
        assert "potica" not in out

    def test_empty_result_still_prints_a_header(self, catalogue, capsys):
        catalogue.print_paths(name="nonexistent")
        assert len(capsys.readouterr().out.splitlines()) == 2
