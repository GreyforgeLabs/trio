# Tranche review handoff

Tranche and Trio remain independent projects. Tranche owns model-assisted
backlog discovery and proposed batch composition. Trio owns acquisition of
revision-bound public evidence and local review coordination. This adapter is
independently authored; it does not vendor Tranche code or model prompts.

## One command, no manual file transfer

Install Trio, initialize state with a nonempty local `installation_id` and a
contributor actor, and enroll the public
repository as described in the [evidence guide](USER_GUIDE.md). Keep the
separately installed Tranche checkout and its runtime data outside Trio's
source tree. Tranche must already contain a fresh, bound report produced by
its ordinary `fetch`, `judge`, `dupes`, `cluster`, and `batches` workflow.
Choose an actual batch ID from that report.

```bash
trio --home "$TRIO_STATE" commands --command 'handoff tranche' --json
trio --home "$TRIO_STATE" handoff tranche --dataset DATASET_ID --tranche-root TRANCHE_CHECKOUT --batch BATCH_ID --actor contributor --read-token-env TRIO_GITHUB_TOKEN --request-budget 100 --json
```

The command reads the selected Tranche installation, validates its current
report binding, transfers a sealed selection internally, captures each PR
with Trio's `pr-comparison` profile, rechecks identities/revisions, and creates
one draft group. It does not invoke a model or resolve a TypeSafe key. Existing
Tranche outputs remain unchanged. Each project can still be used alone.

The GitHub token is selected by environment-variable name and must match the
dataset's enrolled account namespace. Comparison includes closing-issue
GraphQL evidence, so anonymous or insufficiently permitted reads may leave
coverage incomplete. A captured CI result is evidence of an observation,
not an execution of tests by this command.

The original adapter supports Tranche commit
`99ffca6dc635d855ed57e87204f9778a300233cd` (v0.2.1), with exact `tranche.py`
Git blob `d3ad2664cbcd8e0f83626a72dbd9750252d634d4`. It verifies those source
bytes before loading the selected dependency. Unknown or edited versions
fail with `HANDOFF_VERSION`; upgrading support requires a reviewed pin and
compatibility tests. No dependency download, install or automatic update occurs.

This local compatibility candidate also pins the independently reviewed
provider-aware `tranche.py` blob `45ccd80132ff740c96f5b32254385a5b45a8c1f0`,
from candidate tree `a6210e2f2313e7608be6f016a675af01aefc6cdf` based on the
same upstream commit above. This identifies a reviewed source tree, not a
published upstream commit or release. The loader accepts only these two exact
source blobs; it never relaxes the check or downloads an updated dependency.
The tree records provenance; the executed file's bytes are the trust pin.
The provider work remains a separate Tranche change, without vendoring its code.

## What is bound and what remains a proposal

The producer verifies the captured snapshot checksum, matching clusters/dupes
digests, current source/judgment/pair report binding, and recomputed batch
composition. It detects file changes across export. The internal
`trio.tranche-handoff/v1` contract carries source/version digests, selected
public PR metadata, batch identity, and the original uncertain/related-group
diagnostics. Model-generated reviewer prompts are not used as commands.

The provider-aware source uses `trio.tranche-handoff/v2`. It retains the
explicit reviewed base/tree/blob identity and the report's provider descriptor
(adapter, provider ID, requested model, public settings and capabilities),
descriptor fingerprint, selected normalized PR answers, resolved-model claims,
and relevant pair observations. This preserves unsupported/null values and
explicit abstentions, including reasons; it does not reinterpret them as zero
risk, source equivalence or approval. These provider observations remain opaque,
unverified claims, not Trio findings or verified model execution evidence.

Trio reads the provider recorded in the report, without activating a provider
or reading a provider configuration/key file. It checks the descriptor's
fingerprint, recomputes the provider-aware observation binding, and requires
the batches' full report binding and exact recomputed content to match.
Relabelling an old report with changed settings/provider identity is refused.
Changing a separate Tranche configuration file alone does not change an
already-produced report; regenerate it with Tranche before selecting that
configuration's new results. Legacy v1 envelopes and reports remain supported.

The consumer checks repository and PR identities, full base/head SHAs, update
time, open state and public scope. Actual Trio captures supply structured
citations. A final read checks selected revisions immediately before recording
the draft group. Missing or partial comparison components stop group creation
and remain visible in the durable handoff record.

All imported model claims remain unverified. A checksum proves byte integrity,
not authenticity, calibrated confidence, duplicate equivalence or approval.
Even Tranche's `confirmed_groups` label is only a model-consistent suggestion.
Unjudged PRs and standalone uncertain pairs can appear in v3 batches; they do
not become approved findings. The adapter creates no finding, review, merge,
close, contribution, credential, role or publication permission.

## Inspect and resume

Copy the returned handoff `id`. If the response is truncated, use its
`identifiers.id` and inspect with a larger response budget.

```bash
trio --home "$TRIO_STATE" handoff show --id HANDOFF_ID --max-bytes 65536 --json
trio --home "$TRIO_STATE" handoff run --id HANDOFF_ID --read-token-env TRIO_GITHUB_TOKEN --request-budget 100 --json
```

The request budget covers the whole run. `complete: false` and
`outcome: stopped` require inspecting `error` and each captured coverage record.
Budget exhaustion, interruption or missing evidence retain local progress.
Explicitly rerun to resume. A changed head, base, update time or repository
scope requires a fresh Tranche report and handoff instead of silently rebinding
old model claims.

Repeating the same input uses the same handoff identity and group. Batch
ordinals alone are never cache identities: a new source generation produces
a different handoff even if the batch is still named `B001`. Recovery after
an interrupted group write does not duplicate the group or reset human edits.
A completed replay returns recorded observations without new network reads;
it does not certify current GitHub state.

The record includes the combined `snapshot`, `group_id`, `group_event`, and
verified `evidence_refs`. Use the ordinary index/search/retrieve commands on
that snapshot, then write and review findings through the existing workflow.
Evidence references in the group are retained for review and source-scoped
sharing checks. Group notes still require the ordinary sharing review.

For an already transferred versioned envelope, `handoff prepare --dataset
DATASET_ID --path HANDOFF_JSON --actor contributor` is the offline preparation
route; `handoff run` performs live capture. This is optional and is not needed
by `handoff tranche`.

## Current boundaries and verification

This integration stops at evidence-backed review coordination. Source/patch
validation and publication use their existing separate gates. In particular,
Trio contribution acquisition still refuses symlinks, submodules, LFS pointers,
and unsupported source entries. Do not bypass that by unsafe extraction or by
claiming that a review group is a validated source bundle. Omarchy source
trees containing symlinks cannot yet traverse that contribution-acquisition
path unchanged.

Synthetic integration tests cover revision drift, stale generations,
uncertainty preservation, request bounds, partial capture/resume, replay,
crash recovery, unsafe paths, and unrecognized dependency code. The existing
contribution suite verifies symlink/submodule refusal. Tests use no model
credentials, live GitHub calls, or GitHub mutations. Classifier evaluation,
live model/mutation qualification and automatic scheduling are separate work.
The provider-aware compatibility check exercises real, separately installed
source with synthetic observations: default Jev protocol, category-only
offline results, explicit PR/pair abstention, stale provider settings, and
changed batches. All paths stop at draft review groups. Run it explicitly:

```bash
PYTHONPATH=src python tests/test_handoff.py --tranche-root LEGACY_CHECKOUT --tranche-root REVIEWED_PROVIDER_CHECKOUT
```

This opt-in check fails closed for unknown source and uses only synthetic
transports/model responses. It is additional to the ordinary offline test
suite; no third-party source is included in the test distribution.
