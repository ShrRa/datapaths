"""Adding a root by declaring it in the roots file, with no code change.

A new kind of artifact -- plots, reports, logs -- should cost one line of YAML.
Before the fallback in _resolve_root, an unmapped type raised regardless of
what the roots file said, so every call had to repeat root_key=.
"""

from __future__ import annotations

import pytest

from datapaths.artifacts import TYPE_TO_ROOT
from datapaths.exceptions import ArtifactError


@pytest.fixture
def with_plots(repo):
    """The whole setup a new root is supposed to need."""
    plots = repo.root.parent / "store" / "plots"
    plots.mkdir(parents=True)
    repo.write_roots({**repo.roots, "plots": plots})
    repo.roots["plots"] = plots
    return repo


class TestDeclaredRootIsEnough:
    def test_a_type_named_after_a_root_resolves_to_it(self, with_plots):
        dp = with_plots.dp()
        rec = dp.save(b"\x89PNG", name="lc_grid", type="plots", fmt="bin")
        assert rec["root"] == "plots"
        assert (with_plots.roots["plots"] / rec["path"]).exists()

    def test_the_artifact_round_trips(self, with_plots):
        dp = with_plots.dp()
        dp.save(b"\x89PNG", name="lc_grid", type="plots", fmt="bin")
        assert dp["lc_grid"].read_bytes() == b"\x89PNG"

    def test_it_is_listed_and_filterable_by_the_new_type(self, with_plots):
        dp = with_plots.dp()
        dp.save(b"x", name="lc_grid", type="plots", fmt="bin")
        assert [r["name"] for r in dp.list(type="plots")] == ["lc_grid"]

    def test_it_verifies(self, with_plots):
        dp = with_plots.dp()
        dp.save(b"x", name="lc_grid", type="plots", fmt="bin")
        assert [r["status"] for r in dp.verify(type="plots")] == ["OK"]

    def test_register_takes_the_new_type_too(self, with_plots):
        src = with_plots.roots["plots"] / "existing.png"
        src.write_bytes(b"x")
        rec = with_plots.dp().register(
            name="existing", type="plots", src_path=str(src), fmt="bin"
        )
        assert rec["root"] == "plots"

    def test_a_custom_type_is_flat_not_family_nested(self, with_plots):
        """Family nesting is a features-only convention."""
        rec = with_plots.dp().save(b"x", name="a_b_c_d", type="plots", fmt="bin")
        assert rec["path"] == "a_b_c_d.bin"


class TestPrecedence:
    def test_explicit_root_key_still_wins(self, with_plots):
        rec = with_plots.dp().save(
            b"x", name="fig", type="plots", fmt="bin", root_key="misc"
        )
        assert rec["root"] == "misc"

    def test_type_to_root_wins_over_a_same_named_root(self, with_plots):
        """dataprep maps to the data root, and must keep doing so.

        Someone who also defines a 'dataprep' root must not silently see their
        existing dataprep artifacts start landing somewhere new.
        """
        repo = with_plots
        dataprep = repo.root.parent / "store" / "dataprep"
        dataprep.mkdir()
        repo.write_roots({**repo.roots, "dataprep": dataprep})

        assert TYPE_TO_ROOT["dataprep"] == "data"
        rec = repo.dp().save({"a": 1}, name="prepped", type="dataprep", fmt="json")
        assert rec["root"] == "data"

    def test_built_in_types_are_unaffected(self, with_plots, frame):
        rec = with_plots.dp().save(frame, name="a_b_c_d", type="features")
        assert rec["root"] == "features"


class TestFailures:
    def test_an_undeclared_type_still_raises(self, repo):
        with pytest.raises(ArtifactError, match="No root configured for type 'plots'"):
            repo.dp().save(b"x", name="fig", type="plots", fmt="bin")

    def test_that_error_says_how_to_fix_it(self, repo):
        with pytest.raises(ArtifactError, match="add a root named 'plots'"):
            repo.dp().save(b"x", name="fig", type="plots", fmt="bin")

    def test_that_error_names_the_roots_file(self, repo):
        with pytest.raises(ArtifactError, match=repo.roots_file.name):
            repo.dp().save(b"x", name="fig", type="plots", fmt="bin")

    def test_that_error_lists_what_is_known(self, repo):
        with pytest.raises(ArtifactError, match="Known types and roots:.*features"):
            repo.dp().save(b"x", name="fig", type="plots", fmt="bin")

    def test_an_unknown_root_key_lists_the_available_ones(self, repo):
        with pytest.raises(ArtifactError, match="Available:.*models"):
            repo.dp().save(b"x", name="fig", type="misc", fmt="bin", root_key="nowhere")

    def test_a_root_removed_from_the_yaml_is_reported(self, with_plots):
        roots = {k: v for k, v in with_plots.roots.items() if k != "plots"}
        with_plots.write_roots(roots)
        with pytest.raises(ArtifactError, match="No root configured"):
            with_plots.dp().save(b"x", name="fig", type="plots", fmt="bin")
