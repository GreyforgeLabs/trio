# SPDX-License-Identifier: Apache-2.0
"""Build exact allowlisted inputs locally. No Git initialization or upload."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import re

from check_publication import (
    Blocked, audit_source, canonical, read_object, stage_source,
)


def pinned_environment(lock):
    """Review and pin the current public build closure before invoking hooks."""
    if not isinstance(lock, dict):
        raise Blocked("dependency_lock")
    if set(lock) == {"build_tools"}:
        tools = lock["build_tools"]
    elif lock.get("schema") == "trio.dependencies/v1" and isinstance(lock.get("files"), list):
        selected = [entry for entry in lock["files"] if entry.get("role") == "build"]
        tools = {}
        for entry in selected:
            name, version = entry.get("name"), entry.get("version")
            if name in tools or not entry.get("sha256") or not entry.get("source") or not entry.get("review"):
                raise Blocked("dependency_lock")
            tools[name] = version
    else:
        raise Blocked("dependency_lock")
    if not isinstance(tools, dict) or not {"pip", "setuptools", "wheel"} <= set(tools):
        raise Blocked("dependency_lock")
    for name, version in tools.items():
        if not isinstance(name, str) or not isinstance(version, str):
            raise Blocked("dependency_lock")
        try:
            observed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise Blocked("dependency_pin") from None
        if observed != version:
            raise Blocked("dependency_pin")


def load_lock(path):
    if str(path).endswith(".lock"):
        import re
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > 16_777_216:
            raise Blocked("dependency_lock")
        tools = {}
        for line in candidate.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+) --hash=sha256:([a-f0-9]{64})", line.strip())
            if not match or match[1] in tools:
                raise Blocked("dependency_lock")
            tools[match[1]] = match[2]
        return {"build_tools": tools}
    return read_object(path)


def source_archive(stage, allowlist, output, *, prefix="trio-triage-0.1.0"):
    """Deterministic source export from the exact allowlist, never recursive copy."""
    if "/" in prefix or prefix.startswith("."):
        raise Blocked("publication_metadata")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise Blocked("artifact_destination")
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as archive:
        for relative in sorted(allowlist):
            data = (Path(stage) / relative).read_bytes()
            info = tarfile.TarInfo(prefix + "/" + relative)
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    return output


def build(source, allowlist, stage, output, lock, source_manifest=None):
    pinned_environment(lock)
    output = Path(output)
    if output.exists() or any(p.is_symlink() for p in [output, *output.parents]):
        raise Blocked("artifact_destination")
    stage_source(source, allowlist, stage)
    staged_manifest = None
    if source_manifest:
        relative = Path(source_manifest).resolve().relative_to(Path(source).resolve())
        staged_manifest = Path(stage) / relative
    audit_source(stage, allowlist, staged_manifest)
    output.mkdir(mode=0o700, parents=True)
    metadata = tomllib.loads((Path(stage) / "pyproject.toml").read_text())
    version = metadata["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise Blocked("publication_metadata")
    prefix = "trio-triage-" + version
    archive = source_archive(stage, allowlist, output / (prefix + "-source.tar"), prefix=prefix)
    with tempfile.TemporaryDirectory(prefix="public-build-") as temp:
        env = {"PATH": "/usr/bin:/bin", "HOME": temp,
               "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1",
               "SOURCE_DATE_EPOCH": "0", "PIP_CONFIG_FILE": os.devnull}
        try:
            # The backend/dependency versions were checked above; no downloads,
            # credential discovery, inherited environment, or build isolation
            # dependency resolution occurs. Hooks run only from staged inputs.
            result = subprocess.run([
                sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
                "--no-build-isolation", "--disable-pip-version-check",
                "--wheel-dir", str(output.resolve()), str(Path(stage).resolve()),
            ], cwd=temp, env=env, capture_output=True, timeout=120,
               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            raise Blocked("build_execution") from None
        if result.returncode:
            raise Blocked("build_execution")
        try:
            result = subprocess.run([sys.executable,"-c","from setuptools.build_meta import build_sdist; build_sdist("+repr(str(output.resolve()))+")"],cwd=str(Path(stage).resolve()),env=env,capture_output=True,timeout=120,stdin=subprocess.DEVNULL)
        except (OSError,subprocess.TimeoutExpired):raise Blocked("build_execution") from None
        if result.returncode:raise Blocked("build_execution")
    artifacts = sorted(output.iterdir())
    if len([p for p in artifacts if p.suffix == ".whl"]) != 1:
        raise Blocked("build_artifacts")
    return {"schema": "trio.public-build/v1",
            "artifacts": [{"path": p.name, "size": p.stat().st_size,
                           "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in artifacts],
            "release_gates": "NOT_RUN", "publication_ready": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dependency-lock", required=True)
    parser.add_argument("--source-manifest")
    args = parser.parse_args(argv)
    try:
        report = build(args.source, read_object(args.allowlist), args.stage,
                       args.output, load_lock(args.dependency_lock),
                       args.source_manifest)
        print(canonical(report).decode())
        return 0
    except Blocked as error:
        print(canonical({"publication_ready": False, "blocked_check": error.check}).decode())
        return 3
    except Exception:
        print('{"publication_ready":false,"blocked_check":"build_error"}')
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
