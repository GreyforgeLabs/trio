# Publication

The v0.1.0 public release is preserved. Each subsequent release requires fresh
reviews bound to its exact source, artifacts, Git objects and metadata. Tests
and generic scans do not by themselves authorize an upload or official release.

The build_public_artifacts.py script takes an explicit JSON list of reviewed
relative source files, new staging and artifact destinations, and a reviewed
build-tool lock. The lock has build_tools mapping pip, setuptools, and wheel to
exact installed versions. The builder copies only the allowlist, normalizes
permissions, creates a deterministic source export, and builds a wheel from
staged inputs with an empty synthetic home, minimal environment, disabled user
packages, and no dependency downloads. Build hooks and the public dependency
closure require independent review. No developer history, ownership, timestamps,
environment dumps, or recursive workspace copy enter the export.

Build-tool pins are admission checks, not source-rights review or a complete
reproducible-build guarantee. The clean build gate needs an actual isolated
build and installed-artifact smoke test. Wheel and source member lists require
explicit independently reviewed allowlists.

The check_publication.py script validates exact staged files, normalized paths,
provenance coverage, structural token/key/path canaries, and a reviewed pinned
offline scanner. Archive APIs inspect without extraction and bound total bytes,
individual objects, nesting, compression ratios, and entry counts. Traversal,
links, devices, encrypted entries, hidden runtime material, duplicate members,
and mismatched wheel RECORD hashes/file sets fail. Intentionally reviewed
.gitignore, issue-template Markdown, and CI YAML still require exact allowlist
inclusion; other hidden paths are excluded.

The bundled public scanner policy pins Gitleaks 8.30.1 and its executable digest.
The public release archive SHA-256 is
551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb.
It was checked against the public release checksums. Download the binary
separately from the [public release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1);
no executable or scanner report belongs in the package. The checker verifies
binary digest and version before a fixed offline invocation. Scanner output
is captured in a disposable directory; public diagnostics contain generic check
identifiers only. Missing scanner inputs report NOT_RUN. False positives need
review; directory-wide suppression and arbitrary commands/config are excluded.

Provenance is structural evidence only. Imported files need public pinned
repository/commit/path/hash/license/adaptation/test records. Newly authored
files need public review references. A NOT_RUN reference records unfinished
review and does not approve source rights. Manual technical/source-rights and
license reviews remain independent.

The inspect_history API inspects a selected local Git candidate against
approved public refs, reachable object IDs, public identities, and remote URLs.
It never creates, signs, fetches, or pushes. It rejects alternate databases,
grafts, shallow ancestry, replacement/stash/remote refs, unreviewed objects
(including unreachable objects), submodules, LFS material, unsafe config, and
mismatched author/committer/tag identities. Final Git history review is recorded per release. Synthetic tests validate
the inspector; the checker itself never authors Git history.

The candidate_manifest API binds paths, sizes, SHA-256 values, origin classes,
destinations, metadata, and named gate results. verify_binding rechecks exact
bytes immediately before a publication handoff. verify_approval requires
detached signatures checked by an explicitly selected trusted release-key
verifier outside imported receipts. A typed approved:true, untrusted signer
list, agent claim, or hash is insufficient. Distinct technical and
confidentiality reviewers must sign, plus the designated owner must authorize
the exact destinations and metadata. Changing one byte, metadata field, or
destination invalidates approval.

No confidential policy is accepted by these scripts. Owner inspection happens
offline in a separate environment with read-only candidate artifacts. Private
policies and detailed findings never enter source, builds, CI, tests, fixtures,
reports, SBOMs, or packages. Only an approved generic signed receipt binds its
outcome. Source-rights, confidentiality, owner authorization, real history review,
and absent qualification gates remain **NOT_RUN** until actually completed.

The checker always reports publication_ready:false; its exit status covers
generic checks actually performed. It never resolves credentials or uploads.
The signed approval-binding API is a final local handoff check, not an uploader.
Keep independent release decisions separate until the owner authorizes outward
publication.
