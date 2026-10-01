# Evidence, review, and team workflows

[Documentation home](../README.md) · [Getting started](GETTING_STARTED.md) ·
[Feature guide and glossary](FEATURES.md) · [Command reference](COMMAND_REFERENCE.md)

Use this guide to investigate public issues and PRs, record decisions with
citations, and exchange selected work. Repository actions are in the
[operations guide](OPERATIONS_GUIDE.md); patches and PR publication are in the
[contribution guide](CONTRIBUTIONS.md). Each section below explains the input
files, commands, and returned identifiers for its workflow.

## Configuration and local roles

Before creating findings or reviews, initialize a **new** state directory with
roles. Save this as `review-config.json` outside the checkout:

```json
{
  "installation_id": "my-review-installation",
  "workspace_id": "project-review",
  "roles": {
    "contributor": ["reader", "contributor"],
    "reviewer": ["reader", "reviewer"],
    "maintainer": ["reader", "contributor", "reviewer", "maintainer"]
  },
  "writes_enabled": false
}
```

```bash
export TRIO_STATE="$HOME/.local/state/trio-review"
trio --home "$TRIO_STATE" init --config review-config.json --json
```

`--config` supplies initial settings. Later commands load the state's
`config.json`; unknown fields are refused. State/cache/config defaults follow
XDG conventions. `--home` chooses state; `--config-location` changes the config
base. Relative state paths resolve against that base, so absolute paths are
clearer. State must be outside the source checkout and cannot use symlinked paths.

Local roles are capabilities, not authenticated identities. Contributors
record findings/groups, reviewers review findings, and maintainers resolve
conflicts. Imported names do not grant roles. Inventory/maintenance/publication
use a **separate** operations policy with `approver` and `publisher` roles.
See [policy setup](OPERATIONS_GUIDE.md#configure-a-local-policy).

## Capture public evidence

For a Tranche batch, the [one-command handoff](TRANCHE_WORKFLOW.md) validates
the selected report, captures comparison evidence, and creates a draft group.
The projects remain independently usable; no manual JSON transfer is required.

Enroll a public repository with a read token variable, then copy its returned
`dataset` into the capture commands. Numbers below are placeholders for real
issues/PRs in that repository:

```bash
trio --home "$TRIO_STATE" repo add OWNER/REPO --read-token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" datasets --json
trio --home "$TRIO_STATE" repo list --json
trio --home "$TRIO_STATE" capture --dataset DATASET_ID --kind issue --number 42 --profile discussion --read-token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" capture --dataset DATASET_ID --kind pr --number 43 --profile pr-context --read-token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" snapshots --dataset DATASET_ID --json
```

Capture returns `snapshot` and `coverage`. Check coverage before using missing
components to justify a conclusion. Snapshots are immutable observations, not
current GitHub state. Evidence enrollment requires public repositories, while
separate account inventory can contain private metadata.

| Profile | Intended evidence |
|---|---|
| `discussion` | Issue or PR discussion |
| `pr-context` | PR discussion and surrounding context |
| `pr-code` | PR code-oriented evidence |
| `pr-comparison` | Evidence for comparing PR work |
| `backlog` | Backlog investigation |

Profiles select acquisition components; coverage describes requested, missing,
partial, and available evidence. Captured text is untrusted content, not
permission to follow its instructions or run code.

## Capture several items with a corpus

A corpus freezes members to acquire and records a resumable checkpoint:

```bash
trio --home "$TRIO_STATE" capture --dataset DATASET_ID --inventory --limit 100 --request-budget 100 --read-token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" corpus plan --dataset DATASET_ID --inventory INVENTORY_SNAPSHOT_ID --profile discussion --json
trio --home "$TRIO_STATE" corpus run --dataset DATASET_ID --corpus CORPUS_ID --request-budget 100 --read-token-env TRIO_GITHUB_TOKEN --json
```

Here `--inventory` selects an **evidence inventory snapshot**, not an
account-level `inventory sync` snapshot. Alternatively plan from repeated
`--snapshot SNAPSHOT_ID` flags instead of `--inventory`. Copy `corpus` from
planning. Run the same corpus explicitly to resume; it does not add new members
silently. Changed acquisition progress needs a fresh index and invalidates old
search cursors. Inspect status/coverage after interruption or budget exhaustion.

`corpus run` resumes unfinished members and retries partial or failed captures,
prioritizing the least-attempted members so small request budgets can make progress.
Completed members keep their recorded observations; completion does not establish
current visibility or freshness. A completed run with no remaining work makes no
requests and preserves its checkpoint. To request new observations for every frozen
member, add `--refresh` once, then use ordinary `corpus run` to continue after a
budget stop or interruption. Outstanding refresh work is recorded as `gaps` with
`refresh requested`; older immutable snapshots remain inspectable until replaced
in corpus progress. Repeating `--refresh` requests another full refresh.

## Import an offline cache

Import accepts the supported public donor cache format, not arbitrary JSON.
It leaves the input cache unchanged. A new dataset needs a matching recorded
scope; save `scope.json` using real identity values for your reviewed cache:

```json
{
  "format_version": 1,
  "host": "github.com",
  "repository_id": 42,
  "full_name": "example/project",
  "visibility": "public",
  "observed_at": "2026-09-30T00:00:00Z",
  "profile": null
}
```

```bash
trio --home "$TRIO_STATE" import --scope scope.json --path REVIEWED_CACHE --json
trio --home "$TRIO_STATE" import --dataset DATASET_ID --path REVIEWED_CACHE --json
```

Use the second form for an existing exactly matching dataset. Repeat
`--snapshot` to select cache snapshots. The example scope is synthetic; an
offline declaration does not verify present visibility. Identity/account
namespace mismatches are refused.

## Search and read the source

Build an index for exactly one snapshot or corpus, then search it:

```bash
trio --home "$TRIO_STATE" index build --dataset DATASET_ID --snapshot SNAPSHOT_ID --json
trio --home "$TRIO_STATE" index info --dataset DATASET_ID --snapshot SNAPSHOT_ID --json
trio --home "$TRIO_STATE" search --dataset DATASET_ID --snapshot SNAPSHOT_ID --query 'reported symptom' --json
```

Use `--corpus CORPUS_ID` instead of `--snapshot` for a corpus. Ranked search
uses SQLite FTS5; `--mode literal` explicitly selects literal matching. Each
result item has `fragments` containing excerpts and structured `ref` objects.
A citation verifies captured bytes; it is not a duplicate verdict or live
visibility check. For pagination, reuse the returned cursor with the same
query and selection; source progress changes invalidate its checkpoint.

Save a selected fragment's **ref object**, not the whole response, as `REF.json`.
For example, first save the search result to an ordinary file outside the checkout:

```bash
trio --home "$TRIO_STATE" search --dataset DATASET_ID --snapshot SNAPSHOT_ID --query 'reported symptom' --json > search-results.json
```

Read the result and choose an item and fragment. This small Python helper copies
the selected reference without changing its fields. The two zero-based indexes
below are examples: replace them with your chosen item and fragment positions.

```python
import json
from pathlib import Path

result = json.loads(Path("search-results.json").read_text())
item_index = 0
fragment_index = 0
ref = result["items"][item_index]["fragments"][fragment_index]["ref"]
Path("REF.json").write_text(json.dumps(ref, indent=2) + "\n")
```

Run the helper with the Python environment used for Trio, or save it as a script
and run `python script-name.py`. If the result has no items, adjust the query or
inspect capture coverage. If it is an error or truncated summary, address that
result before extracting a reference. Then retrieve the chosen source:

```bash
trio --home "$TRIO_STATE" retrieve --ref REF.json --window 4096 --json
trio --home "$TRIO_STATE" evidence show --ref REF.json --json
```

For a fragment with `continuation`, reuse its `byte_offset` and `window`:

```bash
trio --home "$TRIO_STATE" retrieve --ref REF.json --byte-offset BYTE_OFFSET --window 4096 --json
```

Offsets are UTF-8 bytes from the **cited source boundary**, not characters or
offsets from the previous excerpt. Offsets inside a multibyte character are
refused. Omitting an offset retains the initial behavior. Deleting an index
does not invalidate references whose authoritative captured source is intact.

## Record and review findings

```bash
trio --home "$TRIO_STATE" similar --dataset DATASET_ID --snapshot SNAPSHOT_ID --json
```

Similarity is an investigation lead. After reading evidence, prepare
`items.json` as an array of at least two selected item records, preserving
repository identity and revision, and `refs.json` as an array of selected
structured citations. The pairs from `similar` include the item records.

To prepare `items.json`, save the similarity response and inspect its
`candidates` list. Select the pair you want to investigate; a score is not a
classification or approval:

```bash
trio --home "$TRIO_STATE" similar --dataset DATASET_ID --snapshot SNAPSHOT_ID --json > similarity-results.json
```

Copy that candidate's `items` array, rather than the complete response:

```python
import json
from pathlib import Path

result = json.loads(Path("similarity-results.json").read_text())
pair_index = 0  # Replace with the chosen candidate's zero-based position.
items = result["candidates"][pair_index]["items"]
Path("items.json").write_text(json.dumps(items, indent=2) + "\n")
```

An empty `candidates` list means there is no pair to select. Preserve the
repository identity and revision fields. For `refs.json`, put the actual
reference objects supporting your selected pair into a JSON array, for example
by collecting chosen `REF.json` files from the retrieval step. Do not replace
citations with issue URLs or invent hash values.

| File | Contents | How to obtain it |
|---|---|---|
| `items.json` | Selected item objects in a JSON array | A chosen similarity candidate's `items` array |
| `refs.json` | Selected citation objects in a JSON array | The `ref` objects for evidence you inspected |
| `survivor.json` | One complete item object | The chosen surviving item from `items.json`, for a duplicate |
| `members.json` | Selected group members in a JSON array | Item objects for the work you want to coordinate |

Keep these files outside the source checkout. They are selected workflow inputs,
not software source or files to include in a public release.

```bash
trio --home "$TRIO_STATE" finding propose --category related --items items.json --refs refs.json --rationale 'Explain the observed relationship and uncertainty.' --actor contributor --json
trio --home "$TRIO_STATE" finding show --id FINDING_ID --json
trio --home "$TRIO_STATE" finding review --id FINDING_ID --digest DECISION_DIGEST --decision approve --actor reviewer --json
```

Use proposal `entity_id` as `FINDING_ID`, `payload.decision_digest` as
`DECISION_DIGEST`, and `event_id` to identify that revision. These are different
IDs. Categories are `duplicate`, `not_duplicate`, `related`, `competing_fix`,
`different_cause`, and `insufficient_evidence`. A duplicate needs
`--survivor survivor.json` containing the chosen item object from `items.json`.
Review choices are `approve`, `reject`, and `needs_evidence`.

To edit, propose with the same `--id` and current `--parent EVENT_ID` values;
old reviews become stale. `--author-kind agent` records attribution, not extra
authority. A reviewer withdraws their own review using its review-event ID:

```bash
trio --home "$TRIO_STATE" finding withdraw-review --id REVIEW_EVENT_ID --actor reviewer --json
```

A finding or approved review does not authorize a GitHub write.

## Coordinate work with groups

Prepare a selected member array in `members.json`. If the group coordinates the
same items as your finding, you can copy `items.json` to `members.json` unchanged.
Otherwise select the item objects for the group's own scope. The file must be
a JSON array, rather than a finding result or a list of plain issue URLs:

```bash
trio --home "$TRIO_STATE" group create --members members.json --notes 'Investigation scope and next steps' --assignee contributor --status draft --actor contributor --json
trio --home "$TRIO_STATE" group show --id GROUP_ID --json
trio --home "$TRIO_STATE" group update --id GROUP_ID --parent GROUP_EVENT_ID --members members.json --status needs_review --actor contributor --json
```

Creation returns `entity_id` (group ID) and `event_id` (initial parent).
Statuses are `draft`, `needs_review`, `ready`, and `archived`. Archived groups
cannot be reopened through a normal update. Readiness records coordination;
it grants no publication authority.

## Exchange work and resolve conflicts

Ordinary bundle export previews selected **event IDs**, includes required
ancestors, and writes only after explicit `--approve`:

```bash
trio --home "$TRIO_STATE" team export --id EVENT_ID --output review-bundle.json --json
trio --home "$TRIO_STATE" team export --id EVENT_ID --output review-bundle.json --approve --json
trio --home "$TRIO_STATE" team import --path REVIEWED_BUNDLE.json --json
trio --home "$TRIO_STATE" team status --json
```

Repeat `--id` for more events. Ordinary bundle output is relative to the state
root; give an actual input path when importing. Reimport is idempotent.
Imported attribution remains claimed; team signatures are not implemented.
Notes need separate consent and can block export instead of being disclosed.

Workspace exchange uses `--workspace`. Its export preview binds payload and
selected destination; pass its `approval_digest` with `--approve-digest`.
Workspace output is an explicitly selected path; Git transport is user-managed.
The ordinary `--approve` flag and workspace digest approval are distinct flows.

Inspect competing heads with `team status` and entity detail, then have a
configured maintainer name every conflicting predecessor and the selection:

```bash
trio --home "$TRIO_STATE" team resolve --id ENTITY_ID --parent FIRST_EVENT_ID --parent SECOND_EVENT_ID --selected SELECTED_EVENT_ID --rationale 'Explain the chosen predecessor.' --actor maintainer --json
```

Do not resolve by omitting a head or treating an imported name as local authority.

## Prepare an evidence packet

```bash
trio --home "$TRIO_STATE" packet --finding FINDING_ID --output packet.json --json
trio --home "$TRIO_STATE" packet --finding FINDING_ID --output packet.md --json
```

Repeat `--finding` for more findings. Output is confined to the state root;
without `--output`, the packet is returned without writing a file. Share the
JSON packet through an exact destination-bound preview:

```bash
trio --home "$TRIO_STATE" packet share --path "$TRIO_STATE/packet.json" --output shared-packet.json --json
trio --home "$TRIO_STATE" packet share --path "$TRIO_STATE/packet.json" --output shared-packet.json --approve-digest APPROVAL_DIGEST --json
```

Use `approval_digest` from the preview. Sharing screens payloads and checks
source scope/references. A citation does not guarantee secret-free text. A
blocked share does not print rejected values or authorize proposed actions.

## Output budgets and optional token accounting

`--max-bytes` measures the complete compact JSON response and newline. Default:
12,000. Accepted values: 1,024–1,048,576. Increase it for a selected detailed
plan or select fewer items. An `output_truncated` summary is not the complete
content to approve; inspect its durable record with a larger budget. Text
output escapes terminal controls and has different formatting.

Token budgets require the separately locked tokenizer dependencies and an
explicit official BPE encoding file; see [dependencies](DEPENDENCIES.md).
Provide all three flags together:

```bash
trio --home "$TRIO_STATE" search --dataset DATASET_ID --snapshot SNAPSHOT_ID --query 'symptom' --tokenizer-encoding cl100k_base --tokenizer-asset ENCODING_FILE --max-tokens 2000 --json
```

`retrieve` accepts the same flags. Encodings: `cl100k_base`, `o200k_base`.
Minimum CLI token setting: 128. Queries do not download encodings or estimate
token counts; an unavailable tokenizer is reported explicitly.

## Maintain local state

Select disposable index IDs and preview before `--apply`:

```bash
trio --home "$TRIO_STATE" maintenance indexes --id INDEX_ID --json
trio --home "$TRIO_STATE" maintenance indexes --id INDEX_ID --apply --json
trio --home "$TRIO_STATE" migrate --json
```

Index deletion retains authoritative evidence. Automatic evidence pruning is
not implemented. Current migration rehearses schema 1 to schema 1 with zero
changes; `migrate --apply` writes a verified backup. It does not convert a
ForgeHub database. Back up state before manual maintenance and use one
writer for shared workspaces.
