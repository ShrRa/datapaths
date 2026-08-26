"""The file lock around registry updates.

This is the only test that exercises what filelock is there for. A lost update
here corrupts a committed file -- two pipeline stages finishing together and
one silently discarding the other's entries -- and read-modify-write on a YAML
file has no other protection.

Multiprocessing, not threads: the lock is inter-process, and threads in one
interpreter would not reproduce the race it guards.
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import pytest
import yaml

from datapaths.registry import Registry, read_registry, update_registry_atomic, write_registry


def _append_many(registry_path: str, prefix: str, count: int) -> None:
    """Append `count` artifacts one at a time, each a full read-modify-write."""
    for i in range(count):
        def _upd(reg: Registry, i=i) -> Registry:
            reg.artifacts[f"{prefix}_{i:03d}"] = {
                "type": "misc", "root": "misc",
                "path": f"{prefix}_{i:03d}.json", "format": "json",
            }
            return reg

        update_registry_atomic(Path(registry_path), _upd)


class TestConcurrentUpdates:
    def test_two_processes_do_not_lose_each_other_s_writes(self, tmp_path):
        registry = tmp_path / "artifacts_registry.yaml"
        n = 50

        ctx = mp.get_context("spawn")
        procs = [
            ctx.Process(target=_append_many, args=(str(registry), prefix, n))
            for prefix in ("alpha", "beta")
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)

        assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]

        artifacts = read_registry(registry).artifacts
        assert len(artifacts) == 2 * n
        for prefix in ("alpha", "beta"):
            assert sum(1 for k in artifacts if k.startswith(prefix)) == n

    def test_the_file_is_still_valid_yaml_afterwards(self, tmp_path):
        registry = tmp_path / "artifacts_registry.yaml"
        ctx = mp.get_context("spawn")
        procs = [
            ctx.Process(target=_append_many, args=(str(registry), prefix, 20))
            for prefix in ("a", "b", "c")
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)

        raw = yaml.safe_load(registry.read_text())
        assert raw["registry_version"] == 1
        assert len(raw["artifacts"]) == 60


class TestRegistryIO:
    def test_absent_file_reads_as_an_empty_registry(self, tmp_path):
        reg = read_registry(tmp_path / "nothing.yaml")
        assert reg.version == 1
        assert reg.artifacts == {}

    def test_round_trip(self, tmp_path):
        path = tmp_path / "r.yaml"
        write_registry(path, Registry(version=1, artifacts={"a": {"type": "misc"}}))
        assert read_registry(path).artifacts == {"a": {"type": "misc"}}

    def test_parent_directories_are_created(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "r.yaml"
        write_registry(path, Registry(version=1, artifacts={}))
        assert path.exists()

    def test_version_is_preserved(self, tmp_path):
        path = tmp_path / "r.yaml"
        write_registry(path, Registry(version=3, artifacts={}))
        assert read_registry(path).version == 3

    @pytest.mark.parametrize("body", ["- a\n- b\n", "a string\n"])
    def test_a_non_mapping_registry_raises(self, tmp_path, body):
        path = tmp_path / "r.yaml"
        path.write_text(body)
        with pytest.raises(Exception, match="not a dict"):
            read_registry(path)

    def test_a_non_mapping_artifacts_key_raises(self, tmp_path):
        path = tmp_path / "r.yaml"
        path.write_text("registry_version: 1\nartifacts:\n  - one\n  - two\n")
        with pytest.raises(Exception, match="must be a dict"):
            read_registry(path)

    def test_an_update_returning_the_wrong_type_raises(self, tmp_path):
        path = tmp_path / "r.yaml"
        with pytest.raises(Exception, match="must return Registry"):
            update_registry_atomic(path, lambda reg: {"not": "a registry"})
