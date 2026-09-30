# SPDX-License-Identifier: Apache-2.0
"""Fail-closed local candidate inspection. No publication or confidential policy.

Generic diagnostics expose only check identifiers, never matched content, paths,
scanner stderr, confidential findings, or environment values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import zlib
import subprocess
import tarfile
import tempfile
import zipfile

MAX_FILE = 67_108_864
MAX_TOTAL = 536_870_912
MAX_MEMBERS = 10000
MAX_DEPTH = 3
PROHIBITED_PARTS = {
    ".git", ".env", ".ssh", ".config", "__pycache__", "node_modules",
    "state.sqlite", "credentials",
}
SECRET = re.compile(
    rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    rb"(?i:authorization\s*:\s*bearer)|"
    rb"(?i:(?:access_token|password|api_key)\s*[=:]\s*[^\s]{12,}))"
)
ABSOLUTE_PRIVATE_PATH = re.compile(rb"(?:/(?:home|Users)/[A-Za-z0-9_.-]+/|[A-Z]:\\Users\\)")
REQUIRED_GATES = (
    "source_allowlist", "artifact_allowlist", "provenance", "structural_scan",
    "generic_secret_scanner", "history_and_metadata", "license_review",
    "clean_environment_build", "functional_tests", "diagnostic_canaries",
    "technical_source_rights_review", "owner_confidentiality_review",
    "owner_publication_authorization",
)


class Blocked(Exception):
    def __init__(self, check):
        self.check = check
        super().__init__("candidate blocked")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalized(path):
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise Blocked("unsafe_path")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or "." in p.parts or str(p) != path:
        raise Blocked("unsafe_path")
    if p.parts[0] in {"datasets", "actions", "packets", "cache", "indexes"}:
        raise Blocked("runtime_material")
    approved_hidden = (path == ".gitignore" or
                       (len(p.parts) == 3 and p.parts[:2] == (".github", "ISSUE_TEMPLATE") and
                        not p.parts[-1].startswith(".") and path.endswith(".md")) or
                       (len(p.parts) == 3 and p.parts[:2] == (".github", "workflows") and
                        not p.parts[-1].startswith(".") and path.endswith((".yml", ".yaml"))))
    if any(part in PROHIBITED_PARTS for part in p.parts):
        raise Blocked("unsafe_path")
    if any(part.startswith(".") for part in p.parts) and not approved_hidden:
        raise Blocked("unsafe_path")
    if any(part.endswith((".sqlite", ".db", ".pyc", ".log", "~")) for part in p.parts):
        raise Blocked("runtime_material")
    return path


DISTRIBUTION_ROOTS = {"trio-triage-0.1.0", "trio_triage-0.1.0",
                      "trio-triage-0.2.0", "trio_triage-0.2.0"}


def archive_name(path, *, directory=False):
    # Only this candidate's two conventional distribution roots may precede
    # reviewed hidden community paths. Arbitrary nested hidden paths still fail.
    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise Blocked("unsafe_path")
    parts = PurePosixPath(path).parts
    if (PurePosixPath(path).is_absolute() or ".." in parts or
        "." in parts or str(PurePosixPath(path)) != path):
        raise Blocked("unsafe_path")
    relative = "/".join(parts[1:]) if len(parts) > 1 and parts[0] in DISTRIBUTION_ROOTS else path
    if directory and relative in {".github", ".github/ISSUE_TEMPLATE", ".github/workflows"}:
        return path
    normalized(relative)
    return path


def safe_pax(headers):
    # PAX timestamp extension fields are standard backend metadata, never path
    # or link overrides. Bound spelling/precision/range before accepting them.
    if set(headers) - {"mtime", "atime", "ctime"}:
        raise Blocked("archive_metadata")
    for value in headers.values():
        if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,9})?", value):
            raise Blocked("archive_metadata")
        if float(value) > 253402300799:
            raise Blocked("archive_metadata")


def no_symlink_ancestors(path):
    selected = Path(path)
    if any(p.is_symlink() for p in [selected, *selected.parents]):
        raise Blocked("symlink")
    return selected


def _file(root, relative):
    normalized(relative)
    root = no_symlink_ancestors(root).resolve()
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise Blocked("symlink")
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise Blocked("unsafe_path")
    if path.stat().st_size > MAX_FILE:
        raise Blocked("resource_limit")
    return path


def read_object(path):
    p = no_symlink_ancestors(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > 16_777_216:
        raise Blocked("invalid_manifest")
    try:
        def pairs(items):
            obj = {}
            for key, value in items:
                if key in obj:
                    raise ValueError()
                obj[key] = value
            return obj
        return json.loads(p.read_bytes(), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise Blocked("invalid_manifest") from None


def actual_files(root):
    root = no_symlink_ancestors(root)
    paths = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Blocked("symlink")
        if path.is_file():
            paths.append(normalized(path.relative_to(root).as_posix()))
        elif not path.is_dir():
            raise Blocked("special_file")
    if len(paths) > MAX_MEMBERS:
        raise Blocked("resource_limit")
    return sorted(paths)


def stage_source(source, allowlist, destination):
    """Copy exactly reviewed files into a NEW local staging directory."""
    if not isinstance(allowlist, list) or not allowlist or len(allowlist) != len(set(allowlist)):
        raise Blocked("source_allowlist")
    allowlist = sorted(normalized(x) for x in allowlist)
    destination = Path(destination)
    if destination.exists() or any(p.is_symlink() for p in destination.parents):
        raise Blocked("stage_destination")
    if destination.resolve().is_relative_to(Path(source).resolve()):
        raise Blocked("stage_destination")
    files = [_file(source, x) for x in allowlist]
    if sum(x.stat().st_size for x in files) > MAX_TOTAL:
        raise Blocked("resource_limit")
    destination.mkdir(mode=0o700, parents=True)
    for relative, path in zip(allowlist, files):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy bytes and normalized mode, no ownership/time/xattrs.
        target.write_bytes(path.read_bytes())
        target.chmod(0o644)
    return allowlist


def structural_scan(data):
    if len(data) > MAX_FILE:
        raise Blocked("resource_limit")
    if SECRET.search(data):
        raise Blocked("secret_pattern")
    if ABSOLUTE_PRIVATE_PATH.search(data):
        raise Blocked("private_path")


def _zip_wrapper(raw, archive):
    # Small reviewed wheels need no prefix, comment, extras, ZIP64 or data descriptor.
    # Account for every local record, central record and the terminal directory.
    infos = archive.infolist()
    offset = 0
    for info in sorted(infos, key=lambda item: item.header_offset):
        if info.header_offset != offset or raw[offset:offset + 4] != b"PK\x03\x04":
            raise Blocked("archive_wrapper")
        if offset + 30 > len(raw):
            raise Blocked("archive_wrapper")
        header = struct.unpack_from("<4s5H3I2H", raw, offset)
        flags, method, crc, compressed, size, name_size, extra_size = header[2], header[3], header[6], header[7], header[8], header[9], header[10]
        if flags & 9 or method not in (0, 8) or extra_size or (crc, compressed, size) != (info.CRC, info.compress_size, info.file_size):
            raise Blocked("archive_wrapper")
        name = raw[offset + 30:offset + 30 + name_size]
        try:
            if name.decode("utf-8" if flags & 0x800 else "cp437") != info.filename:
                raise Blocked("archive_wrapper")
        except UnicodeError:
            raise Blocked("archive_wrapper") from None
        start = offset + 30 + name_size
        if size > MAX_FILE or compressed > MAX_FILE or start + compressed > len(raw):
            raise Blocked("resource_limit")
        payload = raw[start:start + compressed]
        if info.is_dir() and (size or compressed):
            raise Blocked("archive_wrapper")
        if method == 0:
            if compressed != size:
                raise Blocked("archive_wrapper")
        else:
            try:
                decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                decoded = decoder.decompress(payload, size + 1)
                if len(decoded) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise Blocked("archive_wrapper")
            except zlib.error:
                raise Blocked("archive_format") from None
        offset = start + compressed
    if offset != archive.start_dir:
        raise Blocked("archive_wrapper")
    central_start = offset
    for info in infos:
        if offset + 46 > len(raw) or raw[offset:offset + 4] != b"PK\x01\x02":
            raise Blocked("archive_wrapper")
        name_size, extra_size, comment_size = struct.unpack_from("<3H", raw, offset + 28)
        if extra_size or comment_size or info.extra or info.comment:
            raise Blocked("archive_wrapper")
        offset += 46 + name_size
    central_size = offset - central_start
    if len(raw) != offset + 22 or raw[offset:offset + 4] != b"PK\x05\x06":
        raise Blocked("archive_wrapper")
    end = struct.unpack_from("<4s4H2IH", raw, offset)
    if end[1:] != (0, 0, len(infos), len(infos), central_size, central_start, 0):
        raise Blocked("archive_wrapper")


def _tar_wrapper(raw):
    if raw.startswith(b"\x1f\x8b"):
        # Only the backend's optional public filename and normal gzip fields.
        if len(raw) < 18 or raw[2] != 8 or raw[3] & ~8:
            raise Blocked("archive_wrapper")
        if raw[3] & 8:
            end = raw.find(b"\0", 10, 267)
            if end < 0:
                raise Blocked("archive_wrapper")
            try:
                archive_name(raw[10:end].decode("ascii"))
            except UnicodeError:
                raise Blocked("archive_wrapper") from None
        try:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decoded = decoder.decompress(raw, MAX_TOTAL + 1)
            if len(decoded) > MAX_TOTAL or decoder.unconsumed_tail:
                raise Blocked("resource_limit")
            if not decoder.eof or decoder.unused_data:
                raise Blocked("archive_wrapper")
            raw = decoded
        except zlib.error:
            raise Blocked("archive_format") from None
    structural_scan(raw)
    return raw


def archive_members(path, *, depth=0, budget=None):
    """Inspect bytes without extracting. Links/devices/traversal/zip bombs fail."""
    budget = budget if budget is not None else {"bytes": 0, "members": 0}
    if depth > MAX_DEPTH:
        raise Blocked("archive_depth")
    import io
    if isinstance(path, bytes):
        raw = path
    else:
        candidate = no_symlink_ancestors(path)
        if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_size > MAX_FILE:
            raise Blocked("resource_limit")
        raw = candidate.read_bytes()
    if len(raw) > MAX_FILE:
        raise Blocked("resource_limit")
    structural_scan(raw)
    entries = []
    member_names = set()
    def register(name):
        if name in member_names:
            raise Blocked("archive_duplicate")
        member_names.add(name)
    if zipfile.is_zipfile(io.BytesIO(raw)):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            _zip_wrapper(raw, archive)
            for info in archive.infolist():
                mode = info.external_attr >> 16
                entry_type = stat.S_IFMT(mode)
                if info.is_dir():
                    if entry_type not in (0, stat.S_IFDIR):
                        raise Blocked("archive_link")
                    register(archive_name(info.filename.rstrip("/"), directory=True))
                    if info.flag_bits & 1:
                        raise Blocked("archive_encrypted")
                    _admit(budget, 0)
                    continue
                name = archive_name(info.filename)
                register(name)
                if stat.S_ISLNK(mode) or (entry_type not in (0, stat.S_IFREG)):
                    raise Blocked("archive_link")
                if info.flag_bits & 1 or info.file_size > MAX_FILE:
                    raise Blocked("resource_limit")
                if info.file_size > 1000000 and info.file_size > max(1, info.compress_size) * 200:
                    raise Blocked("compression_ratio")
                _admit(budget, info.file_size)
                with archive.open(info) as stream:
                    data = stream.read(MAX_FILE + 1)
                if len(data) != info.file_size:
                    raise Blocked("archive_size")
                entries.append((name, data))
    else:
        raw = _tar_wrapper(raw)
        try:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
                for info in archive:
                    safe_pax(info.pax_headers)
                    if info.isdir():
                        register(archive_name(info.name.rstrip("/"), directory=True))
                        _admit(budget, 0)
                        continue
                    name = archive_name(info.name)
                    register(name)
                    if not info.isfile():
                        raise Blocked("archive_link")
                    _admit(budget, info.size)
                    data = archive.extractfile(info).read(MAX_FILE + 1)
                    if len(data) != info.size:
                        raise Blocked("archive_size")
                    entries.append((name, data))
                end = archive.offset
                padding = raw[end:]
                if len(raw) % 512 or not 1024 <= len(padding) <= 10752 or any(padding):
                    raise Blocked("archive_wrapper")
        except tarfile.TarError:
            raise Blocked("archive_format") from None
    names = [name for name, _ in entries]
    if len(names) != len(set(names)):
        raise Blocked("archive_duplicate")
    for name, data in entries:
        structural_scan(data)
        if name.endswith((".zip", ".whl", ".tar", ".tar.gz", ".tgz")):
            archive_members(data, depth=depth + 1, budget=budget)
    return entries


def _admit(budget, size):
    if size < 0 or size > MAX_FILE:
        raise Blocked("resource_limit")
    budget["bytes"] += size
    budget["members"] += 1
    if budget["bytes"] > MAX_TOTAL or budget["members"] > MAX_MEMBERS:
        raise Blocked("resource_limit")


def audit_source(root, allowlist, source_manifest=None):
    if actual_files(root) != sorted(allowlist):
        raise Blocked("source_allowlist")
    total = 0
    for relative in allowlist:
        path = _file(root, relative)
        data = path.read_bytes()
        total += len(data)
        if total > MAX_TOTAL:
            raise Blocked("resource_limit")
        structural_scan(data)
    if source_manifest is not None:
        manifest = read_object(source_manifest)
        entries = manifest.get("files", manifest.get("sources", [])) if isinstance(manifest, dict) else manifest
        if not isinstance(entries, list):
            raise Blocked("provenance")
        mapped = {e.get("destination"): e for e in entries if isinstance(e, dict)}
        if len(mapped) != len(entries):
            raise Blocked("provenance")
        for relative in allowlist:
            if relative == "third_party/source-manifest.json":
                continue
            if relative not in mapped:
                raise Blocked("provenance")
            entry = mapped[relative]
            if entry.get("origin") == "newly-authored":
                if entry.get("license") != "Apache-2.0" or not entry.get("public_review_reference"):
                    raise Blocked("provenance")
            elif not (
                isinstance(entry.get("repository"), str) and
                re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", entry["repository"]) and
                re.fullmatch("[a-f0-9]{40}", entry.get("commit", "")) and
                entry.get("original_path") and
                re.fullmatch("[a-f0-9]{64}", entry.get("source_sha256", "")) and
                entry.get("license") and entry.get("adaptation") and
                isinstance(entry.get("tests"), list)
            ):
                raise Blocked("provenance")
    return {"source_allowlist": "PASS", "structural_scan": "PASS",
            "provenance": "PASS" if source_manifest else "NOT_RUN"}


def audit_artifact(path, allowlist):
    members = archive_members(path)
    if sorted(name for name, _ in members) != sorted(allowlist):
        raise Blocked("artifact_allowlist")
    # A RECORD may list only files present, and each non-RECORD digest must match.
    if str(path).endswith(".whl"):
        import base64, csv, io
        records = [(n, d) for n, d in members if n.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise Blocked("wheel_record")
        contents = dict(members)
        seen = set()
        for row in csv.reader(io.StringIO(records[0][1].decode())):
            if len(row) != 3 or row[0] not in contents or row[0] in seen:
                raise Blocked("wheel_record")
            seen.add(row[0])
            if row[0] == records[0][0]:
                if row[1] or row[2]:
                    raise Blocked("wheel_record")
            else:
                wanted = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(contents[row[0]]).digest()).rstrip(b"=").decode()
                if row[1] != wanted or row[2] != str(len(contents[row[0]])):
                    raise Blocked("wheel_record")
        if seen != set(contents):
            raise Blocked("wheel_record")
    return {"artifact_allowlist": "PASS"}


def run_pinned_scanner(root, executable, policy):
    """Only a reviewed pinned gitleaks binary; stdout/stderr never public."""
    if executable is None or policy is None:
        return {"generic_secret_scanner": "NOT_RUN"}
    if set(policy) != {"name", "version", "executable_sha256"} or policy["name"] != "gitleaks":
        raise Blocked("scanner_policy")
    binary = Path(executable)
    if binary.is_symlink() or not binary.is_file() or sha256(binary.read_bytes()) != policy["executable_sha256"]:
        raise Blocked("scanner_pin")
    with tempfile.TemporaryDirectory(prefix="public-scan-") as temp:
        env = {"PATH": "/usr/bin:/bin", "HOME": temp, "LANG": "C.UTF-8"}
        try:
            version = subprocess.run([str(binary.resolve()), "version"], cwd=temp,
                                     env=env, capture_output=True, timeout=20,
                                     stdin=subprocess.DEVNULL)
            if version.returncode or version.stdout.decode().strip() != policy["version"]:
                raise Blocked("scanner_pin")
            result = subprocess.run([
                str(binary.resolve()), "detect", "--no-git", "--source",
                str(Path(root).resolve()), "--report-format", "json",
                "--report-path", str(Path(temp) / "report.json"), "--redact",
            ], cwd=temp, env=env, capture_output=True, timeout=120,
               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            raise Blocked("scanner_execution") from None
        if result.returncode != 0:
            raise Blocked("generic_secret_scanner")
    return {"generic_secret_scanner": "PASS", "scanner_version": policy["version"]}


def inspect_history(repository, policy):
    """Read all intended public objects using an explicitly approved policy.

    No Git creation, hooks, signing, fetch or push occurs. The policy contains
    public approved object IDs, refs, remotes and identities, never confidential
    comparison lists. New/changed history requires a new review policy.
    """
    root = Path(repository).resolve()
    git_dir = root / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise Blocked("history_layout")
    if set(policy) != {"refs", "objects", "identities", "remotes"}:
        raise Blocked("history_policy")
    for relative in ("objects/info/alternates", "info/grafts", "shallow"):
        if (git_dir / relative).exists():
            raise Blocked("history_ancestry")
    for name in ("modules", "lfs"):
        if (git_dir / name).exists():
            raise Blocked("history_external_objects")
    if any(p.is_symlink() for p in git_dir.rglob("*")):
        raise Blocked("history_layout")
    config = git_dir / "config"
    if config.exists():
        if config.stat().st_size > 16_777_216:
            raise Blocked("history_layout")
        raw_config = config.read_bytes()
        if re.search(rb"(?im)^\s*\[(?:include|includeIf|credential|filter|gpg)\b|^\s*(?:sshCommand|fsmonitor|external|url|pushurl)\s*=", raw_config):
            # URL keys are reviewed below through a minimal parsed local config;
            # remote URLs alone are permitted, executable/include settings are not.
            dangerous = re.search(rb"(?im)^\s*\[(?:include|includeIf|credential|filter|gpg)\b|^\s*(?:sshCommand|fsmonitor|external)\s*=", raw_config)
            if dangerous:
                raise Blocked("history_config")
        structural_scan(raw_config)
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
           "LANG": "C.UTF-8"}
    def git(*args, data=None):
        try:
            result = subprocess.run(
                ["git", "--no-pager", "--no-replace-objects", "-c",
                 "core.hooksPath=" + os.devnull, "-C", str(root), *args],
                input=data, capture_output=True, env=env, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            raise Blocked("history_execution") from None
        if result.returncode or len(result.stdout) > MAX_TOTAL:
            raise Blocked("history_execution")
        return result.stdout
    refs = {}
    for line in git("for-each-ref", "--format=%(refname) %(objectname)").decode().splitlines():
        ref, oid = line.split(" ", 1)
        if ref.startswith(("refs/replace/", "refs/remotes/")) or ref == "refs/stash":
            raise Blocked("history_refs")
        if not ref.startswith(("refs/heads/", "refs/tags/")):
            raise Blocked("history_refs")
        refs[ref] = oid
    if refs != policy["refs"] or not refs:
        raise Blocked("history_refs")
    remotes = {}
    for name in git("remote").decode().splitlines():
        # A read-only config query never contacts the remote.
        urls = git("config", "--get-all", "remote." + name + ".url").decode().splitlines()
        configuration = git("config", "--local", "--list").decode().splitlines()
        pushes = [line.split("=", 1)[1] for line in configuration
                  if line.startswith("remote." + name + ".pushurl=")]
        remotes[name] = {"urls": urls, "pushurls": pushes}
        if any(not u.startswith("https://github.com/") for u in urls + pushes):
            raise Blocked("history_remotes")
    if remotes != policy["remotes"]:
        raise Blocked("history_remotes")
    object_ids = set()
    for line in git("rev-list", "--objects", *refs).decode().splitlines():
        oid = line.split(" ", 1)[0]
        if not re.fullmatch("[a-f0-9]{40,64}", oid):
            raise Blocked("history_objects")
        object_ids.add(oid)
    if object_ids != set(policy["objects"]):
        raise Blocked("history_objects")
    # Unreachable content must not enter a distributable Git directory either.
    all_ids = {line.split()[0] for line in git("cat-file", "--batch-all-objects",
               "--batch-check=%(objectname)").decode().splitlines()}
    if all_ids != object_ids:
        raise Blocked("history_objects")
    total = 0
    identities = set(policy["identities"])
    for oid in sorted(object_ids):
        kind = git("cat-file", "-t", oid).decode().strip()
        size = int(git("cat-file", "-s", oid).decode())
        total += size
        if size > MAX_FILE or total > MAX_TOTAL:
            raise Blocked("resource_limit")
        data = git("cat-file", "-p", oid)
        structural_scan(data)
        if kind in ("commit", "tag"):
            for line in data.split(b"\n\n", 1)[0].splitlines():
                if line.startswith((b"author ", b"committer ", b"tagger ")):
                    identity = re.sub(rb" [-0-9]+ [+-][0-9]{4}$", b"", line.split(b" ", 1)[1]).decode()
                    if identity not in identities:
                        raise Blocked("history_identity")
        if kind == "tree":
            for line in data.decode().splitlines():
                if line.startswith("160000 "):
                    raise Blocked("history_submodule")
                header, name = line.split("\t", 1)
                if name == ".gitattributes":
                    attributes = git("cat-file", "-p", header.split()[2])
                    for attribute_line in attributes.splitlines():
                        if not attribute_line.lstrip().startswith(b"#") and re.search(rb"(?:^|\s)filter\s*=\s*lfs(?:\s|$)", attribute_line):
                            raise Blocked("history_external_objects")
        # A source-code/documentation mention is not an LFS pointer object.
        if kind == "blob" and re.match(rb"version https://git-lfs\.github\.com/spec/v1(?:\r?\n|$)", data):
            raise Blocked("history_external_objects")
    return {"history_and_metadata": "PASS"}


def candidate_manifest(root, artifacts, destinations, metadata, gates=None):
    if not isinstance(metadata, dict) or not destinations or any(
        not isinstance(x, str) or not x.startswith("https://") for x in destinations
    ):
        raise Blocked("publication_metadata")
    from urllib.parse import urlsplit
    import ipaddress
    for destination in destinations:
        parsed = urlsplit(destination)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise Blocked("publication_metadata")
        if parsed.hostname in {"localhost", "localhost.localdomain"} or parsed.hostname.endswith((".local", ".internal")):
            raise Blocked("publication_metadata")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise Blocked("publication_metadata")
    structural_scan(canonical({"metadata": metadata, "destinations": destinations}))
    root = Path(root)
    if set(artifacts) != set(destinations):
        raise Blocked("artifact_binding")
    entries = []
    for destination in sorted(destinations):
        spec = artifacts[destination]
        if set(spec) != {"path", "origin"} or spec["origin"] not in {"source-export", "wheel", "sdist", "documentation", "release-metadata"}:
            raise Blocked("artifact_binding")
        path = _file(root, spec["path"])
        entries.append({"path": spec["path"], "size": path.stat().st_size,
                        "sha256": sha256(path.read_bytes()),
                        "origin": spec["origin"], "destination": destination})
    manifest = {"schema": "trio.publication-manifest/v1", "artifacts": entries,
                "destinations": sorted(destinations), "metadata": metadata,
                "gates": {k: (gates or {}).get(k, "NOT_RUN") for k in REQUIRED_GATES}}
    manifest["digest"] = sha256(canonical(manifest))
    return manifest


def verify_binding(root, manifest):
    content = {k: v for k, v in manifest.items() if k != "digest"}
    if sha256(canonical(content)) != manifest.get("digest"):
        raise Blocked("artifact_binding")
    for entry in manifest["artifacts"]:
        path = _file(root, entry["path"])
        if path.stat().st_size != entry["size"] or sha256(path.read_bytes()) != entry["sha256"]:
            raise Blocked("artifact_binding")
    return True


def verify_approval(root, manifest, receipt, verify_signature=None):
    """No trust in approved:true. Caller provides approved release-key verifier.

    The callback verifies detached signatures against keys selected OUTSIDE
    imported receipts. Receipt files cannot supply trusted keys or commands.
    This function does not upload anything.
    """
    verify_binding(root, manifest)
    if (verify_signature is None or not isinstance(receipt, dict) or
        set(receipt) != {"binding", "signatures"} or len(canonical(receipt)) > 16_777_216):
        raise Blocked("release_approval")
    binding = {"manifest_digest": manifest["digest"],
               "destinations": manifest["destinations"],
               "metadata": manifest["metadata"]}
    if receipt.get("binding") != binding:
        raise Blocked("artifact_binding")
    approvals = receipt.get("signatures", [])
    required = {"technical_source_rights_review", "owner_confidentiality_review",
                "owner_publication_authorization"}
    accepted = {}
    for approval in approvals:
        if set(approval) != {"role", "reviewer", "signature"} or approval["role"] not in required:
            raise Blocked("release_approval")
        payload = canonical({"binding": binding, "role": approval["role"],
                             "reviewer": approval["reviewer"]})
        try:
            verified = verify_signature(approval["role"], approval["reviewer"], payload,
                                        approval["signature"])
        except Exception:
            raise Blocked("release_approval") from None
        if verified is not True:
            raise Blocked("release_approval")
        if approval["role"] in accepted:
            raise Blocked("release_approval")
        accepted[approval["role"]] = approval["reviewer"]
    if set(accepted) != required or accepted["technical_source_rights_review"] == accepted["owner_confidentiality_review"]:
        raise Blocked("release_approval")
    if any(manifest["gates"].get(g) != "PASS" for g in REQUIRED_GATES if g not in required):
        raise Blocked("release_gates")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect local reviewed candidates; never publish.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--allowlist", required=True)
    parser.add_argument("--source-manifest")
    parser.add_argument("--scanner")
    parser.add_argument("--scanner-policy")
    parser.add_argument("--history")
    parser.add_argument("--history-policy")
    parser.add_argument("--artifact")
    parser.add_argument("--artifact-allowlist")
    args = parser.parse_args(argv)
    try:
        allowlist = read_object(args.allowlist)
        gates = audit_source(args.source, allowlist, args.source_manifest)
        policy = read_object(args.scanner_policy) if args.scanner_policy else None
        gates.update(run_pinned_scanner(args.source, args.scanner, policy))
        if args.history or args.history_policy:
            if not args.history or not args.history_policy:
                raise Blocked("history_policy")
            gates.update(inspect_history(args.history, read_object(args.history_policy)))
        if args.artifact or args.artifact_allowlist:
            if not args.artifact or not args.artifact_allowlist:
                raise Blocked("artifact_allowlist")
            gates.update(audit_artifact(args.artifact, read_object(args.artifact_allowlist)))
        report = {"schema": "trio.publication-check/v1",
                  "checks": {k: gates.get(k, "NOT_RUN") for k in REQUIRED_GATES},
                  "publication_ready": False}
        print(canonical(report).decode())
        performed = [k for k in REQUIRED_GATES if k in gates]
        return 0 if all(gates[k] == "PASS" for k in performed) else 1
    except Blocked as error:
        print(canonical({"schema": "trio.publication-check/v1",
                         "publication_ready": False, "blocked_check": error.check}).decode())
        return 3
    except Exception:
        print('{"schema":"trio.publication-check/v1","publication_ready":false,"blocked_check":"inspection_error"}')
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
