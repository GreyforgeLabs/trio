# SPDX-License-Identifier: Apache-2.0
"""Public synthetic publication canaries and exact-byte authorization tests."""
import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_publication as publication
import build_public_artifacts as builder
import install_public_scanner as scanner_installer


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "README.md").write_text("Synthetic public documentation.\n")

    def assert_blocked(self, check, fn, *args, **kwargs):
        with self.assertRaises(publication.Blocked) as error:
            fn(*args, **kwargs)
        self.assertEqual(error.exception.check, check)
        self.assertEqual(str(error.exception), "candidate blocked")

    def tar(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, data, kind in entries:
                info = tarfile.TarInfo(name)
                if kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "outside"
                    archive.addfile(info)
                else:
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        return output.getvalue()

    def zip(self, entries):
        output = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(output, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, data, mode in entries:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                archive.writestr(info, data)
        return output.getvalue()

    def test_exact_source_stage_and_unlisted_content_omitted(self):
        (self.source / "unselected.txt").write_text("Synthetic unselected note")
        stage = self.root / "stage"
        publication.stage_source(self.source, ["README.md"], stage)
        self.assertEqual(publication.actual_files(stage), ["README.md"])
        self.assertEqual(publication.audit_source(stage, ["README.md"])["source_allowlist"], "PASS")
        (stage / "extra.txt").write_text("Extra")
        self.assert_blocked("source_allowlist", publication.audit_source, stage, ["README.md"])

    def test_stage_rejects_traversal_hidden_duplicate_and_symlink(self):
        for path in ("../outside", "/absolute", "a\\b", ".env", ".git/config", "cache/token"):
            with self.subTest(path=path):
                self.assertRaises(publication.Blocked, publication.normalized, path)
        self.assert_blocked("source_allowlist", publication.stage_source,
                            self.source, ["README.md", "README.md"], self.root / "stage")
        (self.source / "link.txt").symlink_to(self.source / "README.md")
        self.assert_blocked("symlink", publication.stage_source, self.source,
                            ["link.txt"], self.root / "stage")

    def test_approved_public_hidden_files(self):
        self.assertEqual(publication.normalized(".gitignore"), ".gitignore")
        self.assertEqual(publication.normalized(".github/ISSUE_TEMPLATE/bug.md"), ".github/ISSUE_TEMPLATE/bug.md")
        self.assertRaises(publication.Blocked, publication.normalized, ".github/credentials.json")

    def test_structural_canaries_never_appear_in_errors(self):
        synthetic = ("gh" + "p_" + "SYNTHETICNONLIVE" * 3).encode()
        private_path = ("/" + "home/synthetic-user/private.txt").encode()
        self.assert_blocked("secret_pattern", publication.structural_scan, synthetic)
        self.assert_blocked("private_path", publication.structural_scan, private_path)

    def test_provenance_missing_duplicate_review_reference(self):
        path = self.source / "manifest.json"
        path.write_text(json.dumps({"files": []}))
        self.assert_blocked("provenance", publication.audit_source,
                            self.source, ["README.md", "manifest.json"], path)
        entry = {"destination": "README.md", "origin": "newly-authored",
                 "license": "Apache-2.0", "public_review_reference": "NOT_RUN"}
        path.write_text(json.dumps({"files": [entry, entry]}))
        self.assert_blocked("provenance", publication.audit_source,
                            self.source, ["README.md", "manifest.json"], path)

    def test_archive_links_traversal_and_duplicates(self):
        self.assert_blocked("unsafe_path", publication.archive_members,
                            self.tar([("../outside", b"x", "file")]))
        self.assert_blocked("archive_link", publication.archive_members,
                            self.tar([("link", b"", "symlink")]))
        # zip duplicate entries are rejected independently of content.
        raw = self.zip([("file.txt", b"x", stat.S_IFREG | 0o644),
                        ("file.txt", b"x", stat.S_IFREG | 0o644)])
        self.assert_blocked("archive_duplicate", publication.archive_members, raw)

    def test_archive_zip_symlink_and_nested_canary(self):
        raw = self.zip([("link", b"outside", stat.S_IFLNK | 0o777)])
        self.assert_blocked("archive_link", publication.archive_members, raw)
        leak = ("gh" + "p_" + "SYNTHETICNONLIVE" * 3).encode()
        inner = self.zip([("note.txt", leak, stat.S_IFREG | 0o644)])
        outer = self.zip([("nested.zip", inner, stat.S_IFREG | 0o644)])
        self.assert_blocked("secret_pattern", publication.archive_members, outer)

    def test_archive_wrapper_canaries_and_opaque_prefix_trailer_refuse(self):
        import gzip
        tar = self.tar([("public.txt", b"public", "file")])
        zipped = self.zip([("public.txt", b"public", stat.S_IFREG | 0o644)])
        canary = ("gh" + "p_" + "SYNTHETICNONLIVE" * 3).encode()
        for raw in (tar, zipped, gzip.compress(tar, mtime=0)):
            self.assertEqual(publication.archive_members(raw), [("public.txt", b"public")])
            self.assert_blocked("secret_pattern", publication.archive_members, raw + canary)
            for changed in (raw + b"unreviewed-trailer", b"unreviewed-prefix" + raw):
                with self.subTest(format=raw[:4],position=changed[:4]):
                    with self.assertRaises(publication.Blocked) as error:publication.archive_members(changed)
                    self.assertNotIn("unreviewed", str(error.exception))
        self.assert_blocked("archive_wrapper", publication.archive_members, gzip.compress(tar,mtime=0)+gzip.compress(tar,mtime=0))
        self.assert_blocked("archive_wrapper", publication.archive_members, tar+tar)
        # Two 512-byte end blocks may cross the final 10KiB record boundary.
        boundary=self.tar([("public.txt",b"x"*9216,"file")])
        self.assertEqual(publication.archive_members(boundary),[("public.txt",b"x"*9216)])
    def test_zip_comments_extra_and_gaps_are_not_unreviewed_payload(self):
        raw=self.zip([("public.txt",b"public",stat.S_IFREG|0o644)])
        for wrapper in (raw[:-2]+b"\x04\x00note",raw+b"\x00"):
            self.assert_blocked("archive_wrapper",publication.archive_members,wrapper)
        output=io.BytesIO()
        with zipfile.ZipFile(output,"w") as archive:
            info=zipfile.ZipInfo("public.txt");info.extra=b"\x01\x00\x00\x00";archive.writestr(info,b"public")
        self.assert_blocked("archive_wrapper",publication.archive_members,output.getvalue())
    def test_zip_deflate_eof_cannot_hide_second_compressed_payload(self):
        import struct,zlib
        output=io.BytesIO()
        with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr("public.txt",b"public")
        raw=output.getvalue();self.assertEqual(publication.archive_members(raw),[("public.txt",b"public")])
        central=raw.index(b"PK\x01\x02");end=raw.index(b"PK\x05\x06")
        hidden=zlib.compress(("gh"+"p_"+"SYNTHETICNONLIVE"*3).encode())
        changed=bytearray(raw[:central]+hidden+raw[central:])
        compressed=struct.unpack_from("<I",raw,18)[0]
        struct.pack_into("<I",changed,18,compressed+len(hidden))
        struct.pack_into("<I",changed,central+len(hidden)+20,compressed+len(hidden))
        struct.pack_into("<I",changed,end+len(hidden)+16,central+len(hidden))
        self.assert_blocked("archive_wrapper",publication.archive_members,bytes(changed))
        self.assert_blocked("archive_wrapper",publication.archive_members,self.zip([("dir/",b"ignored",stat.S_IFDIR|0o755)]))
    def test_archive_members_bounded_including_directories(self):
        raw = self.zip([("a/", b"", stat.S_IFDIR | 0o755),
                        ("b/", b"", stat.S_IFDIR | 0o755)])
        with patch.object(publication, "MAX_MEMBERS", 1):
            self.assert_blocked("resource_limit", publication.archive_members, raw)

    def test_archive_bounded_before_read(self):
        path = self.root / "large.tar"
        path.write_bytes(b"not read")
        with patch.object(publication, "MAX_FILE", 2):
            with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")):
                self.assert_blocked("resource_limit", publication.archive_members, path)

    def test_nested_depth_bounded(self):
        raw = self.zip([("file.txt", b"x", stat.S_IFREG | 0o644)])
        for _ in range(4):
            raw = self.zip([("nested.zip", raw, stat.S_IFREG | 0o644)])
        self.assert_blocked("archive_depth", publication.archive_members, raw)

    def test_artifact_exact_allowlist(self):
        path = self.root / "source.tar"
        path.write_bytes(self.tar([("public.txt", b"public", "file")]))
        self.assertEqual(publication.audit_artifact(path, ["public.txt"]), {"artifact_allowlist": "PASS"})
        self.assert_blocked("artifact_allowlist", publication.audit_artifact, path, ["public.txt", "extra"])

    def wheel(self, corrupt=False):
        body = b"Synthetic package"
        name = "trio_triage/__init__.py"
        record = "trio_triage-0.1.0.dist-info/RECORD"
        digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode()
        rows = f"{name},sha256={digest},{len(body)}\n{record},,\n".encode()
        raw = self.zip([(name, body + (b"changed" if corrupt else b""), stat.S_IFREG | 0o644),
                        (record, rows, stat.S_IFREG | 0o644)])
        path = self.root / "synthetic.whl"
        path.write_bytes(raw)
        return path, [name, record]

    def test_wheel_record_binds_every_file(self):
        path, names = self.wheel()
        publication.audit_artifact(path, names)
        path, names = self.wheel(corrupt=True)
        self.assert_blocked("wheel_record", publication.audit_artifact, path, names)

    def manifest(self):
        artifact = self.root / "candidate.tar"
        artifact.write_bytes(self.tar([("public.txt", b"public", "file")]))
        destination = "https://example.invalid/releases/trio-triage-0.1.0"
        return publication.candidate_manifest(
            self.root, {destination: {"path": artifact.name, "origin": "source-export"}},
            [destination], {"version": "0.1.0"},
            {key: "PASS" for key in publication.REQUIRED_GATES})

    def receipt(self, manifest):
        return {"binding": {"manifest_digest": manifest["digest"],
                            "destinations": manifest["destinations"],
                            "metadata": manifest["metadata"]},
                "signatures": [
                    {"role": role, "reviewer": reviewer, "signature": "synthetic-valid"}
                    for role, reviewer in (
                        ("technical_source_rights_review", "synthetic-technical"),
                        ("owner_confidentiality_review", "synthetic-owner"),
                        ("owner_publication_authorization", "synthetic-owner"),
                    )]}

    def verifier(self, role, reviewer, payload, signature):
        return signature == "synthetic-valid"

    def test_manifest_byte_change_invalidates_binding(self):
        manifest = self.manifest()
        publication.verify_binding(self.root, manifest)
        (self.root / "candidate.tar").write_bytes(b"changed")
        self.assert_blocked("artifact_binding", publication.verify_binding, self.root, manifest)

    def test_untrusted_approved_boolean_is_not_authority(self):
        manifest = self.manifest()
        self.assert_blocked("release_approval", publication.verify_approval,
                            self.root, manifest, {"approved": True})
        self.assert_blocked("release_approval", publication.verify_approval,
                            self.root, manifest, self.receipt(manifest))

    def test_signed_exact_approval_binding_and_distinct_reviews(self):
        manifest = self.manifest()
        receipt = self.receipt(manifest)
        self.assertTrue(publication.verify_approval(self.root, manifest, receipt, self.verifier))
        receipt["binding"]["destinations"] = ["https://example.invalid/different"]
        self.assert_blocked("artifact_binding", publication.verify_approval,
                            self.root, manifest, receipt, self.verifier)
        receipt = self.receipt(manifest)
        receipt["signatures"][0]["reviewer"] = "synthetic-owner"
        self.assert_blocked("release_approval", publication.verify_approval,
                            self.root, manifest, receipt, self.verifier)

    def test_destination_or_metadata_change_invalidates_signature_binding(self):
        manifest = self.manifest()
        receipt = self.receipt(manifest)
        manifest["metadata"] = {"version": "0.1.1"}
        manifest["digest"] = publication.sha256(publication.canonical({k: v for k, v in manifest.items() if k != "digest"}))
        self.assert_blocked("artifact_binding", publication.verify_approval,
                            self.root, manifest, receipt, self.verifier)

    def test_not_run_gate_blocks_even_signed_approval(self):
        manifest = self.manifest()
        manifest["gates"]["generic_secret_scanner"] = "NOT_RUN"
        manifest["digest"] = publication.sha256(publication.canonical({k: v for k, v in manifest.items() if k != "digest"}))
        self.assert_blocked("release_gates", publication.verify_approval,
                            self.root, manifest, self.receipt(manifest), self.verifier)

    def test_missing_scanner_honest_not_run(self):
        self.assertEqual(publication.run_pinned_scanner(self.source, None, None),
                         {"generic_secret_scanner": "NOT_RUN"})

    def test_scanner_pin_refuses_arbitrary_binary(self):
        policy = {"name": "gitleaks", "version": "8.30.1",
                  "executable_sha256": "0" * 64}
        self.assert_blocked("scanner_pin", publication.run_pinned_scanner,
                            self.source, sys.executable, policy)

    def test_current_pinned_scanner_clean_and_seeded_failure(self):
        binary = Path("/tmp/trio-gitleaks")
        if not binary.is_file():
            self.skipTest("Pinned public scanner not installed in synthetic test environment")
        policy = publication.read_object(Path(__file__).resolve().parents[1] / "scripts/secret-scanner-policy.json")
        self.assertEqual(publication.run_pinned_scanner(self.source, binary, policy)["generic_secret_scanner"], "PASS")
        synthetic = "gh" + "p_" + "SYNTHETICNONLIVE" * 3
        (self.source / "synthetic.txt").write_text(synthetic)
        self.assert_blocked("generic_secret_scanner", publication.run_pinned_scanner,
                            self.source, binary, policy)

    def test_diagnostics_never_leak_seeded_value_or_path(self):
        synthetic = "gh" + "p_" + "SYNTHETICNONLIVE" * 3
        (self.source / "README.md").write_text(synthetic)
        allow = self.root / "allow.json"
        allow.write_text('["README.md"]')
        result = subprocess.run([sys.executable, str(Path(publication.__file__)),
                                 "--source", str(self.source), "--allowlist", str(allow)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 3)
        self.assertNotIn(synthetic, result.stdout + result.stderr)
        self.assertNotIn(str(self.source), result.stdout + result.stderr)

    def test_manifest_duplicate_keys_refuse(self):
        path = self.root / "duplicate.json"
        path.write_text('{"approved":false,"approved":true}')
        self.assert_blocked("invalid_manifest", publication.read_object, path)

    def test_deterministic_source_export(self):
        stage = self.root / "stage"
        publication.stage_source(self.source, ["README.md"], stage)
        a = builder.source_archive(stage, ["README.md"], self.root / "a.tar")
        b = builder.source_archive(stage, ["README.md"], self.root / "b.tar")
        self.assertEqual(a.read_bytes(), b.read_bytes())
        members = publication.archive_members(a)
        self.assertEqual(members[0][0], "trio-triage-0.1.0/README.md")

    def test_history_rejects_external_ancestry_without_git_execution(self):
        repo = self.root / "repo"
        (repo / ".git/objects/info").mkdir(parents=True)
        (repo / ".git/objects/info/alternates").write_text("synthetic external path")
        with patch.object(publication.subprocess, "run", side_effect=AssertionError("unexpected git")):
            self.assert_blocked("history_ancestry", publication.inspect_history,
                                repo, {"refs": {}, "objects": [], "identities": [], "remotes": {}})

    def test_history_reachable_objects_refs_identity_binding(self):
        repo = self.root / "repo"
        (repo / ".git").mkdir(parents=True)
        oid = "a" * 40
        data = b"tree " + b"b" * 40 + b"\nauthor Synthetic Reviewer <public@example.invalid> 0 +0000\ncommitter Synthetic Reviewer <public@example.invalid> 0 +0000\n\nPublic synthetic commit\n"
        policy = {"refs": {"refs/heads/main": oid}, "objects": [oid],
                  "identities": ["Synthetic Reviewer <public@example.invalid>"],
                  "remotes": {}}
        def git(command, **kwargs):
            args = command[command.index(str(repo)) + 1:]
            if args[0] == "for-each-ref":
                out = ("refs/heads/main " + oid + "\n").encode()
            elif args[0] == "remote":
                out = b""
            elif args[0] == "rev-list":
                out = (oid + "\n").encode()
            elif args[:2] == ["cat-file", "--batch-all-objects"]:
                out = (oid + "\n").encode()
            elif args[:2] == ["cat-file", "-t"]:
                out = b"commit\n"
            elif args[:2] == ["cat-file", "-s"]:
                out = str(len(data)).encode()
            elif args[:2] == ["cat-file", "-p"]:
                out = data
            else:
                self.fail("Unexpected git read")
            return subprocess.CompletedProcess(command, 0, out, b"")
        with patch.object(publication.subprocess, "run", side_effect=git):
            self.assertEqual(publication.inspect_history(repo, policy),
                             {"history_and_metadata": "PASS"})
            policy["identities"] = []
            self.assert_blocked("history_identity", publication.inspect_history, repo, policy)

    def test_history_lfs_checks_actual_pointer_and_attributes_not_source_mentions(self):
        repo=self.root/"repo";(repo/".git").mkdir(parents=True)
        tree="a"*40;blob="b"*40;filename="public.py"
        content=Path(publication.__file__).read_bytes()
        policy={"refs":{"refs/heads/main":tree},"objects":[tree,blob],"identities":[],"remotes":{}}
        def git(command,**kwargs):
            args=command[command.index(str(repo))+1:]
            if args[0]=="for-each-ref":out=("refs/heads/main "+tree+"\n").encode()
            elif args[0]=="remote":out=b""
            elif args[0]=="rev-list" or args[:2]==["cat-file","--batch-all-objects"]:out=(tree+"\n"+blob+"\n").encode()
            else:
                oid=args[-1];data=("100644 blob "+blob+"\t"+filename+"\n").encode() if oid==tree else content
                if args[:2]==["cat-file","-t"]:out=b"tree\n" if oid==tree else b"blob\n"
                elif args[:2]==["cat-file","-s"]:out=str(len(data)).encode()
                elif args[:2]==["cat-file","-p"]:out=data
                else:self.fail("Unexpected git read")
            return subprocess.CompletedProcess(command,0,out,b"")
        with patch.object(publication.subprocess,"run",side_effect=git):
            self.assertEqual(publication.inspect_history(repo,policy),{"history_and_metadata":"PASS"})
            content=b"version https://git-lfs.github.com/spec/v1\noid sha256:"+b"a"*64+b"\nsize 1\n"
            self.assert_blocked("history_external_objects",publication.inspect_history,repo,policy)
            filename=".gitattributes";content=b"*.bin filter=lfs diff=lfs merge=lfs -text\n"
            self.assert_blocked("history_external_objects",publication.inspect_history,repo,policy)
            content=b"file#part filter=lfs\n"
            self.assert_blocked("history_external_objects",publication.inspect_history,repo,policy)
            content=b"# Documentation mentions filter=lfs\n*.txt text\n"
            self.assertEqual(publication.inspect_history(repo,policy),{"history_and_metadata":"PASS"})
    def test_source_export_reviewed_hidden_paths_under_known_root(self):
        template = self.source / ".github" / "ISSUE_TEMPLATE" / "bug.md"
        template.parent.mkdir(parents=True)
        template.write_text("Synthetic bug template.")
        (self.source / ".gitignore").write_text("*.pyc\n")
        allowlist = [".github/ISSUE_TEMPLATE/bug.md", ".gitignore", "README.md"]
        stage = self.root / "hidden-stage"
        publication.stage_source(self.source, allowlist, stage)
        archive = builder.source_archive(stage, allowlist, self.root / "hidden-source.tar")
        expected = ["trio-triage-0.1.0/" + x for x in sorted(allowlist)]
        self.assertEqual(sorted(n for n, _ in publication.archive_members(archive)), expected)
        publication.audit_artifact(archive, expected)

    def test_backend_pax_timestamps_and_hidden_directories(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            for name in ("trio_triage-0.1.0", "trio_triage-0.1.0/.github",
                         "trio_triage-0.1.0/.github/ISSUE_TEMPLATE"):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.pax_headers = {"mtime": "1790764800.125"}
                archive.addfile(info)
            info = tarfile.TarInfo("trio_triage-0.1.0/.github/ISSUE_TEMPLATE/bug.md")
            info.pax_headers = {"mtime": "1790764800.125", "atime": "0", "ctime": "1790764800.123456789"}
            info.size = 6
            archive.addfile(info, io.BytesIO(b"public"))
        self.assertEqual(publication.archive_members(output.getvalue()),
                         [("trio_triage-0.1.0/.github/ISSUE_TEMPLATE/bug.md", b"public")])

    def test_unsupported_pax_overrides_refuse_even_safe_looking_path(self):
        for headers in ({"path": "trio_triage-0.1.0/README.md"},
                        {"linkpath": "README.md"}, {"comment": "unreviewed"},
                        {"mtime": "NaN"}, {"mtime": "999999999999.0"}):
            with self.subTest(headers=headers):
                output = io.BytesIO()
                with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    info = tarfile.TarInfo("trio_triage-0.1.0/README.md")
                    info.pax_headers = headers
                    info.size = 1
                    archive.addfile(info, io.BytesIO(b"x"))
                self.assert_blocked("archive_metadata", publication.archive_members, output.getvalue())

    def test_hidden_admission_does_not_allow_arbitrary_or_nested_roots(self):
        for name in ("unreviewed/.gitignore",
                     "unreviewed/.github/ISSUE_TEMPLATE/bug.md",
                     "trio_triage-0.1.0/.github/ISSUE_TEMPLATE/.hidden.md",
                     "trio_triage-0.1.0/.github/ISSUE_TEMPLATE/extra/.hidden.md",
                     "trio_triage-0.1.0/.github/credentials.json",
                     "trio_triage-0.1.0/.git/config",
                     "trio_triage-0.1.0/../.gitignore"):
            with self.subTest(name=name):
                self.assert_blocked("unsafe_path", publication.archive_members,
                                    self.tar([(name, b"public", "file")]))

    def test_backend_pax_directories_count_toward_archive_limit(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name in ("trio_triage-0.1.0", "trio_triage-0.1.0/.github"):
                info = tarfile.TarInfo(name)
                info.type = tarfile.DIRTYPE
                info.pax_headers = {"mtime": "1790764800.125"}
                archive.addfile(info)
        with patch.object(publication, "MAX_MEMBERS", 1):
            self.assert_blocked("resource_limit", publication.archive_members, output.getvalue())


    def test_source_root_and_ancestor_symlinks_refuse_before_staging(self):
        linked = self.root / "linked-source"
        linked.symlink_to(self.source, target_is_directory=True)
        destination = self.root / "not-created"
        self.assert_blocked("symlink", publication.stage_source,
                            linked, ["README.md"], destination)
        self.assertFalse(destination.exists())
        nested = self.source / "nested"
        nested.mkdir()
        (nested / "README.md").write_text("Synthetic public documentation.")
        self.assert_blocked("symlink", publication.stage_source,
                            linked / "nested", ["README.md"], destination)
        self.assertFalse(destination.exists())

    def test_selected_manifest_symlink_ancestor_refuses_before_read(self):
        (self.source / "allow.json").write_text('["README.md"]')
        linked = self.root / "linked-manifest-parent"
        linked.symlink_to(self.source, target_is_directory=True)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected read")):
            self.assert_blocked("symlink", publication.read_object, linked / "allow.json")


    def test_zip_slash_suffix_cannot_hide_symlink_or_device_mode(self):
        for kind in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFREG):
            with self.subTest(kind=kind):
                raw = self.zip([("link/", b"", kind | 0o777)])
                self.assert_blocked("archive_link", publication.archive_members, raw)
        for kind in (0, stat.S_IFDIR):
            with self.subTest(allowed=kind):
                raw = self.zip([("ordinary/", b"", kind | 0o755)])
                self.assertEqual(publication.archive_members(raw), [])


    def test_duplicate_directories_and_directory_file_aliases_refuse(self):
        for entries in (
            [("a/", b"", stat.S_IFDIR | 0o755), ("a/", b"", stat.S_IFDIR | 0o755)],
            [("a/", b"", stat.S_IFDIR | 0o755), ("a", b"public", stat.S_IFREG | 0o644)],
        ):
            with self.subTest(format="zip", entries=entries):
                self.assert_blocked("archive_duplicate", publication.archive_members,
                                    self.zip(entries))
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for name, data, mode in entries:
                    info = tarfile.TarInfo(name.rstrip("/"))
                    if stat.S_ISDIR(mode):
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    else:
                        info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
            with self.subTest(format="tar", entries=entries):
                self.assert_blocked("archive_duplicate", publication.archive_members,
                                    output.getvalue())



    def test_scanner_installer_accepts_pinned_decompressed_binary_size(self):
        binary = b"S" * scanner_installer.BINARY_SIZE
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            info = tarfile.TarInfo("gitleaks")
            info.size = len(binary)
            archive.addfile(info, io.BytesIO(binary))
        raw = output.getvalue()
        destination = self.root / "scanner"
        with patch.object(scanner_installer.urllib.request, "urlopen", return_value=io.BytesIO(raw)), \
             patch.object(scanner_installer, "ARCHIVE_SHA", hashlib.sha256(raw).hexdigest()), \
             patch.object(scanner_installer, "BINARY_SHA", hashlib.sha256(binary).hexdigest()):
            scanner_installer.install(destination)
        self.assertEqual(destination.stat().st_size, 21958840)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), hashlib.sha256(binary).hexdigest())


if __name__ == "__main__":
    unittest.main()
