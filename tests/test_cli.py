"""The `datapaths` console script.

Driven through subprocess rather than by calling main() directly: the entry
point, the argument wiring, and the JSON on stdout are the contract, and a
consumer's shell script sees exactly this.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")


def run(repo, *args, expect_ok=True):
    proc = subprocess.run(
        [sys.executable, "-m", "datapaths.cli", *args],
        cwd=repo.root, capture_output=True, text=True,
    )
    if expect_ok:
        assert proc.returncode == 0, proc.stderr
    return proc


@pytest.fixture
def stocked(repo, frame):
    dp = repo.dp()
    dp.save(frame, name="bazin_train_s01_c01", type="features", tags=["v02", "bazin"])
    dp.save(frame.assign(flux=1.0), name="potica_train_s01_c01", type="features", tags=["v02"])
    dp.save({"a": 1}, name="lgbm", type="models", fmt="json", tags=["v01"])
    return repo


class TestList:
    def test_outputs_parseable_json(self, stocked):
        rows = json.loads(run(stocked, "list").stdout)
        assert {r["name"] for r in rows} == {
            "bazin_train_s01_c01", "potica_train_s01_c01", "lgbm"
        }

    def test_type_filter(self, stocked):
        rows = json.loads(run(stocked, "list", "--type", "models").stdout)
        assert [r["name"] for r in rows] == ["lgbm"]

    def test_name_filter(self, stocked):
        rows = json.loads(run(stocked, "list", "--name", "potica").stdout)
        assert len(rows) == 1

    def test_comma_separated_tags_filter_on_all_of_them(self, stocked):
        """A shell user types --tag v02,bazin; it must mean both, not neither."""
        rows = json.loads(run(stocked, "list", "--tag", "v02,bazin").stdout)
        assert [r["name"] for r in rows] == ["bazin_train_s01_c01"]

    def test_text_filter(self, stocked):
        rows = json.loads(run(stocked, "list", "--text", "lgbm").stdout)
        assert len(rows) == 1


class TestVerify:
    def test_all_ok(self, stocked):
        rows = json.loads(run(stocked, "verify").stdout)
        assert {r["status"] for r in rows} == {"OK"}

    def test_detects_drift(self, stocked):
        target = stocked.roots["features"] / "bazin" / "bazin_train_s01_c01.parquet"
        target.write_bytes(b"tampered")
        rows = json.loads(run(stocked, "verify").stdout)
        bad = [r for r in rows if r["status"] == "HASH_MISMATCH"]
        assert [r["name"] for r in bad] == ["bazin_train_s01_c01"]

    def test_repeated_name_flags_accumulate(self, stocked):
        rows = json.loads(
            run(stocked, "verify", "--name", "lgbm", "--name", "potica_train_s01_c01").stdout
        )
        assert len(rows) == 2


class TestRegister:
    def test_registers_a_file_under_a_root(self, repo, tmp_path):
        src = repo.roots["misc"] / "notes.json"
        src.write_text('{"a": 1}')
        rec = json.loads(
            run(repo, "register", "--name", "notes", "--type", "misc",
                "--file", str(src), "--fmt", "json", "--tag", "V02").stdout
        )
        assert rec["tags"] == ["v02"]
        assert repo.dp().get("notes") is not None

    def test_copy_into_canonical(self, repo, tmp_path):
        src = tmp_path / "outside.json"
        src.write_text("{}")
        run(repo, "register", "--name", "adopted", "--type", "misc",
            "--file", str(src), "--fmt", "json", "--copy-into-canonical")
        assert (repo.roots["misc"] / "adopted.json").exists()


class TestFailureModes:
    def test_no_subcommand_exits_nonzero(self, repo):
        assert run(repo, expect_ok=False).returncode != 0

    def test_unknown_format_is_rejected_by_argparse(self, repo):
        proc = run(repo, "register", "--name", "x", "--type", "misc",
                   "--file", "/tmp/x", "--fmt", "zarr", expect_ok=False)
        assert proc.returncode != 0
        assert "invalid choice" in proc.stderr

    def test_missing_source_reports_the_error(self, repo):
        proc = run(repo, "register", "--name", "x", "--type", "misc",
                   "--file", "/nonexistent/file.json", "--fmt", "json", expect_ok=False)
        assert proc.returncode != 0
        assert "does not exist" in proc.stderr


class TestEnvOverrides:
    def test_repo_root_env_var_lets_the_cli_run_from_anywhere(self, stocked, tmp_path, monkeypatch):
        import os

        env = {**os.environ, "DATAPATHS_REPO_ROOT": str(stocked.root)}
        proc = subprocess.run(
            [sys.executable, "-m", "datapaths.cli", "list"],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )
        assert proc.returncode == 0, proc.stderr
        assert len(json.loads(proc.stdout)) == 3


class TestConsoleScript:
    def test_the_installed_entry_point_works(self, stocked):
        """Covers the [project.scripts] wiring, which `-m datapaths.cli` skips."""
        script = shutil.which("datapaths", path=str(Path(sys.executable).parent))
        if script is None:
            pytest.skip("console script not on PATH (package not installed)")
        proc = subprocess.run(
            [script, "list", "--type", "models"],
            cwd=stocked.root, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert [r["name"] for r in json.loads(proc.stdout)] == ["lgbm"]
