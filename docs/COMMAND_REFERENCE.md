# Complete command reference

[Documentation home](../README.md) · [Getting started](GETTING_STARTED.md) · [Feature guide](FEATURES.md)

This reference covers all **66** current Trio command leaves. Arguments, defaults,
choices, effects, and schemas were checked against the parser/catalog. It documents
the current public Trio CLI. Start with the [quickstart](GETTING_STARTED.md) if
you are installing it for the first time.

## Global options

| Option | Meaning | Default |
|---|---|---|
| `--home PATH` | Select local state outside the checkout; absolute paths are easiest to follow. | XDG state location |
| `--config-location PATH` | Select the configuration base, which also anchors relative state paths. | XDG config location |
| `--json` | Return one compact JSON object suitable for scripts and agents. | Text display |
| `--max-bytes N` | Limit the complete JSON response and newline; 1,024–1,048,576. | 12,000 |
| `--help` | Show syntax for the selected command without executing it. | — |

Global options can be placed before the command or on its subcommand. All commands
except `commands` and `init` require initialized state. Uppercase IDs in guides are placeholders.
Repeated options such as `--parent` or `--snapshot` preserve an explicit selection.

## Effects and exit codes

`read-local` reads saved state; `read-github` makes GitHub reads; `write-local`
records local state; `write-github` can change GitHub; `sandbox-execute` runs selected
validation commands in an offline container. The reference reports maximum declared
effects. Conditional local writes are identified by `--path`, `--output`, or `--apply`.
Preview/plan/review do not authorize later GitHub writes on their own.

| Exit | Meaning |
|---|---|
| 0 | Completed without a reported attention condition |
| 1 | Attention: partial acquisition, pending/stopped work, conflicts, or truncated output |
| 2 | Invalid invocation, configuration, or input |
| 3 | Refused by a gate or unmet precondition |
| 4 | Transport failure, failed write, or uncertain write |
| 5 | Internal error |

JSON errors contain `schema: "trio.error/v1"` and `error.code`/`error.message`.
Inspect durable records before retrying an uncertain write. Full reference details are also
available with `trio commands --command 'FAMILY LEAF' --json`.

## Command index

- [`trio commands`](#commands)
- [`trio status`](#status)
- [`trio doctor`](#doctor)
- [`trio datasets`](#datasets)
- [`trio init`](#init)
- [`trio repo add`](#repo-add)
- [`trio repo list`](#repo-list)
- [`trio capture`](#capture)
- [`trio import`](#import)
- [`trio snapshots`](#snapshots)
- [`trio corpus plan`](#corpus-plan)
- [`trio corpus run`](#corpus-run)
- [`trio index build`](#index-build)
- [`trio index info`](#index-info)
- [`trio search`](#search)
- [`trio retrieve`](#retrieve)
- [`trio evidence show`](#evidence-show)
- [`trio similar`](#similar)
- [`trio group create`](#group-create)
- [`trio group update`](#group-update)
- [`trio group show`](#group-show)
- [`trio finding propose`](#finding-propose)
- [`trio finding show`](#finding-show)
- [`trio finding review`](#finding-review)
- [`trio finding withdraw-review`](#finding-withdraw-review)
- [`trio team export`](#team-export)
- [`trio team import`](#team-import)
- [`trio team status`](#team-status)
- [`trio team resolve`](#team-resolve)
- [`trio packet`](#packet)
- [`trio packet share`](#packet-share)
- [`trio action plan`](#action-plan)
- [`trio action inspect`](#action-inspect)
- [`trio action authorize`](#action-authorize)
- [`trio action execute`](#action-execute)
- [`trio action reconcile`](#action-reconcile)
- [`trio maintenance indexes`](#maintenance-indexes)
- [`trio migrate`](#migrate)
- [`trio inventory sync`](#inventory-sync)
- [`trio inventory snapshots`](#inventory-snapshots)
- [`trio inventory list`](#inventory-list)
- [`trio inventory show`](#inventory-show)
- [`trio inventory drift`](#inventory-drift)
- [`trio ops policy`](#ops-policy)
- [`trio ops plan`](#ops-plan)
- [`trio ops inspect`](#ops-inspect)
- [`trio ops approve`](#ops-approve)
- [`trio ops execute`](#ops-execute)
- [`trio ops reconcile`](#ops-reconcile)
- [`trio contribution intake`](#contribution-intake)
- [`trio contribution list`](#contribution-list)
- [`trio contribution show`](#contribution-show)
- [`trio contribution acquire`](#contribution-acquire)
- [`trio contribution patch`](#contribution-patch)
- [`trio contribution validate`](#contribution-validate)
- [`trio contribution plan`](#contribution-plan)
- [`trio contribution inspect`](#contribution-inspect)
- [`trio contribution approve`](#contribution-approve)
- [`trio contribution publish`](#contribution-publish)
- [`trio contribution reconcile`](#contribution-reconcile)
- [`trio contribution revise`](#contribution-revise)
- [`trio contribution refresh`](#contribution-refresh)

## commands

Discover commands and declared effects; select one full command for its argument details.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.commands/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--command` | no | — |

Inspect help: `trio commands --help`.

## status

Inspect initialization, write configuration, operations policy, and recorded validation status.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.status/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio status --help`.

## doctor

Check initialization and SQLite FTS5 support alongside the current policy.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.doctor/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio doctor --help`.

## datasets

List enrolled public evidence datasets.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.datasets/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio datasets --help`.

## init

Create a new empty local state installation, optionally using a reviewed configuration file.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.init/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--config` | no | — |

Inspect help: `trio init --help`.

## repo add

Enroll a currently verified public GitHub repository as an evidence dataset.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.dataset/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `repository` | yes | — |
| `--read-token-env` | no | — |

Inspect help: `trio repo add --help`.

## repo list

List enrolled public evidence datasets.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.datasets/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio repo list --help`.

## capture

Capture one real issue/PR or enumerate an evidence inventory; inspect returned coverage.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.capture/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--kind` | no | choices `issue`, `pr` |
| `--number` | no | integer |
| `--inventory` | no | default `False`; flag; takes no value |
| `--limit` | no | default `100`; integer |
| `--profile` | no | default `discussion`; choices `discussion`, `pr-context`, `pr-code`, `pr-comparison`, `backlog` |
| `--request-budget` | no | integer |
| `--read-token-env` | no | — |

Inspect help: `trio capture --help`.

## import

Import a reviewed supported public cache, selecting an existing dataset or matching scope.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.import/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | no | — |
| `--scope` | no | — |
| `--path` | yes | — |
| `--snapshot` | no | repeatable |

Inspect help: `trio import --help`.

## snapshots

List the evidence snapshots for a dataset.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.snapshots/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |

Inspect help: `trio snapshots --help`.

## corpus plan

Freeze members from an evidence inventory or explicitly selected snapshots.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.corpus/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--inventory` | no | — |
| `--snapshot` | no | repeatable |
| `--profile` | no | default `discussion` |

Inspect help: `trio corpus plan --help`.

## corpus run

Acquire or explicitly resume that frozen corpus under a request budget.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.corpus-run/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--corpus` | yes | — |
| `--read-token-env` | no | — |
| `--request-budget` | no | integer |

Inspect help: `trio corpus run --help`.

## index build

Build a disposable search index from one snapshot or corpus.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.index-build/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--snapshot` | no | — |
| `--corpus` | no | — |
| `--replace` | no | default `False`; flag; takes no value |

Choose exactly one: `--snapshot`, `--corpus`.

Inspect help: `trio index build --help`.

## index info

Inspect the index for the selected captured evidence.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.index-info/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--snapshot` | no | — |
| `--corpus` | no | — |

Choose exactly one: `--snapshot`, `--corpus`.

Inspect help: `trio index info --help`.

## search

Search the selected captured evidence with ranked FTS5 or literal matching.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.query/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--snapshot` | no | — |
| `--corpus` | no | — |
| `--query` | yes | — |
| `--mode` | no | default `ranked`; choices `ranked`, `literal` |
| `--cursor` | no | — |
| `--max-tokens` | no | integer |
| `--tokenizer-encoding` | no | choices `cl100k_base`, `o200k_base` |
| `--tokenizer-asset` | no | — |

Choose exactly one: `--snapshot`, `--corpus`.

Inspect help: `trio search --help`.

## retrieve

Read a selected verified citation; continue using a UTF-8 byte offset from its boundary.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.retrieve/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--ref` | yes | — |
| `--window` | no | default `4096`; integer |
| `--byte-offset` | no | integer |
| `--max-tokens` | no | integer |
| `--tokenizer-encoding` | no | choices `cl100k_base`, `o200k_base` |
| `--tokenizer-asset` | no | — |

Inspect help: `trio retrieve --help`.

## evidence show

Read a selected verified citation using the normal initial retrieval window.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.retrieve/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--ref` | yes | — |

Inspect help: `trio evidence show --help`.

## similar

Return title-similarity investigation leads; these are not duplicate verdicts.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.similar/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--dataset` | yes | — |
| `--snapshot` | yes | — |

Inspect help: `trio similar --help`.

## group create

Record selected members, assignee, notes, and coordination status.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.group-create/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--actor` | yes | — |
| `--members` | yes | — |
| `--notes` | no | default `` |
| `--assignee` | no | — |
| `--status` | no | default `draft`; choices `draft`, `needs_review`, `ready`, `archived` |

Inspect help: `trio group create --help`.

## group update

Update an existing work group against its current event parents.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.group-update/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--actor` | yes | — |
| `--members` | yes | — |
| `--notes` | no | default `` |
| `--assignee` | no | — |
| `--status` | no | default `draft`; choices `draft`, `needs_review`, `ready`, `archived` |
| `--id` | yes | — |
| `--parent` | yes | repeatable |

Inspect help: `trio group update --help`.

## group show

Inspect current group head events.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.group-show/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |

Inspect help: `trio group show --help`.

## finding propose

Record a versioned classification and rationale for at least two selected items.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.finding-propose/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--actor` | yes | — |
| `--category` | yes | — |
| `--items` | yes | — |
| `--refs` | yes | — |
| `--rationale` | yes | — |
| `--author-kind` | no | default `human`; choices `human`, `agent` |
| `--id` | no | — |
| `--parent` | no | repeatable |
| `--survivor` | no | — |

Inspect help: `trio finding propose --help`.

## finding show

Inspect finding revisions, digests, review state, conflicts, and staleness.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.finding/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |

Inspect help: `trio finding show --help`.

## finding review

Review the exact current decision digest as approve, reject, or needs_evidence.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.finding-review/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--actor` | yes | — |
| `--id` | yes | — |
| `--digest` | yes | — |
| `--decision` | yes | choices `approve`, `reject`, `needs_evidence` |

Inspect help: `trio finding review --help`.

## finding withdraw-review

Withdraw a review recorded by the same local reviewer; use its review event ID.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.finding-withdraw-review/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--actor` | yes | — |
| `--id` | yes | — |

Inspect help: `trio finding withdraw-review --help`.

## team export

Preview/export selected event IDs; ordinary bundles use --approve, workspace output uses --approve-digest.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.team-export/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | repeatable |
| `--output` | yes | — |
| `--approve` | no | default `False`; flag; takes no value |
| `--workspace` | no | default `False`; flag; takes no value |
| `--approve-digest` | no | — |

Inspect help: `trio team export --help`.

## team import

Validate and import a reviewed bundle or explicitly selected workspace files idempotently.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.team-import/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--path` | yes | — |
| `--workspace` | no | default `False`; flag; takes no value |

Inspect help: `trio team import --help`.

## team status

Inspect event count and conflicting finding/review heads.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.team-status/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio team status --help`.

## team resolve

Have a local maintainer explicitly resolve the named conflicting predecessors.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.team-resolve/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--actor` | yes | — |
| `--id` | yes | — |
| `--parent` | yes | repeatable |
| `--rationale` | yes | — |
| `--selected` | yes | — |

Inspect help: `trio team resolve --help`.

## packet

Create a selected review packet; --output writes JSON or readable Markdown inside state.

Declared effect: `read-local/write-local-with-output`. Network: `none`.
Output schema: `trio.packet/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--finding` | no | repeatable |
| `--output` | no | — |

Inspect help: `trio packet --help`.

## packet share

Preview a screened JSON packet and write only after exact destination-bound approval.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.packet-share/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--path` | yes | — |
| `--output` | yes | — |
| `--approve-digest` | no | — |

Inspect help: `trio packet share --help`.

## action plan

Prepare an experimental evidence-bound comment/close/reopen plan; this is separate from ops.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.action-plan/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--target` | yes | — |
| `--expected` | yes | — |
| `--operation` | yes | choices `comment`, `close`, `reopen` |
| `--text` | yes | — |
| `--finding-digest` | no | — |
| `--read-token-env` | no | — |

Inspect help: `trio action plan --help`.

## action inspect

Inspect the experimental action journal.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.action-journal/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |

Inspect help: `trio action inspect --help`.

## action authorize

Record exact local authorization for an experimental action; live execution remains disabled.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.action-authorize/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--digest` | yes | — |
| `--actor` | yes | — |

Inspect help: `trio action authorize --help`.

## action execute

Experimental live action adapter is disabled in the current CLI and returns ACTION_DISABLED.

Declared effect: `write-github+write-local`. Network: `github-write`.
Output schema: `trio.action-journal/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--actor` | yes | — |

Inspect help: `trio action execute --help`.

## action reconcile

Experimental live action adapter is disabled in the current CLI; use ops for supported maintenance.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.action-journal/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--read-token-env` | no | — |

Inspect help: `trio action reconcile --help`.

## maintenance indexes

Select disposable index IDs, preview them, and remove only with --apply; evidence is retained.

Declared effect: `read-local/write-local-with-apply`. Network: `none`.
Output schema: `trio.maintenance/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | no | repeatable |
| `--apply` | no | default `False`; flag; takes no value |

Inspect help: `trio maintenance indexes --help`.

## migrate

Rehearse schema 1 to schema 1 with no changes; --apply creates a verified backup, not a ForgeHub converter.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.migrate/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--apply` | no | default `False`; flag; takes no value |

Inspect help: `trio migrate --help`.

## inventory sync

Read account or organization collections into a local, possibly partial snapshot.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.inventory-sync/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--token-env` | yes | — |
| `--organization` | no | — |
| `--repository-limit` | no | default `100`; integer |
| `--item-limit` | no | default `1000`; integer |
| `--request-budget` | no | default `100`; integer |

Inspect help: `trio inventory sync --help`.

## inventory snapshots

List recorded account/organization inventory snapshots.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.inventory-snapshots/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio inventory snapshots --help`.

## inventory list

Read a bounded inventory collection, optionally continuing with its next_cursor.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.inventory-list/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--snapshot` | yes | — |
| `--kind` | no | default `repositories`; choices `repositories`, `forks`, `pulls`, `issues`, `notifications`, `workflow_runs`, `releases` |
| `--repository` | no | — |
| `--limit` | no | default `20`; integer |
| `--cursor` | no | — |

Inspect help: `trio inventory list --help`.

## inventory show

Inspect a repository and collection coverage in one inventory snapshot.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.inventory-repository/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--snapshot` | yes | — |
| `--repository` | yes | — |

Inspect help: `trio inventory show --help`.

## inventory drift

Compare two snapshots from the same account and scope without deletion claims from partial data.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.inventory-drift/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--before` | yes | — |
| `--after` | yes | — |

Inspect help: `trio inventory drift --help`.

## ops policy

Inspect the operations policy; --path explicitly replaces it with reviewed JSON.

Declared effect: `read-local/write-local-with-path`. Network: `none`.
Output schema: `trio.operations-policy/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--path` | no | — |

Inspect help: `trio ops policy --help`.

## ops plan

Prepare one of nine maintenance actions for an exact repository and target.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.maintenance-plan/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--token-env` | yes | — |
| `--operation` | yes | choices `notification-ack`, `issue-label`, `issue-comment`, `issue-close`, `issue-reopen`, `pr-ready`, `pr-close`, `pr-update-branch`, `pr-merge` |
| `--repository` | no | — |
| `--number` | no | integer |
| `--thread` | no | — |
| `--text` | no | — |
| `--labels` | no | — |
| `--merge-method` | no | default `merge`; choices `merge`, `squash`, `rebase` |

Inspect help: `trio ops plan --help`.

## ops inspect

Inspect the selected maintenance plan and its journal.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.maintenance-inspect/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |

Inspect help: `trio ops inspect --help`.

## ops approve

Record an approver decision bound to the exact maintenance plan digest and policy.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.operation-approval/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--actor` | yes | — |
| `--digest` | yes | — |

Inspect help: `trio ops approve --help`.

## ops execute

Execute the approved maintenance plan with fresh identity, permission, and target checks.

Declared effect: `write-github+write-local`. Network: `github-write`.
Output schema: `trio.maintenance-journal/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |
| `--actor` | yes | — |

Inspect help: `trio ops execute --help`.

## ops reconcile

Read GitHub to reconcile a pending/uncertain maintenance journal without replaying writes.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.maintenance-journal/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |

Inspect help: `trio ops reconcile --help`.

## contribution intake

Start from a real public issue or a non-stale, non-conflicting local finding ID.
Finding items and cited sources must match the selected repository's stable
identity. Intake records the exact revision and digests without granting
validation or publication authority.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.contribution/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--repository` | yes | — |
| `--issue` | no | integer |
| `--finding` | no | — |
| `--token-env` | yes | — |

Choose exactly one: `--issue`, `--finding`.

Inspect help: `trio contribution intake --help`.

## contribution list

List local contribution records and their stages.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.contributions/v1`. Explicit authorization declared: no.

No command-specific arguments.

Inspect help: `trio contribution list --help`.

## contribution show

Inspect a local contribution record by contribution ID.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.contribution/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |

Inspect help: `trio contribution show --help`.

## contribution acquire

Acquire verified public Git objects for an exact base SHA/branch under a request budget.

Preserves regular/executable files and relative symlinks ending at tracked
in-tree regular files. Unsafe, dangling, cyclic, directory-target, and overlong
links are refused. Caps remain 5,000 files, 16 MiB per blob, and 64 MiB total;
the request budget covers three metadata reads plus one read per file.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.contribution-acquire/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |
| `--base` | yes | — |
| `--base-branch` | yes | — |
| `--request-budget` | no | default `1000`; integer |

Inspect help: `trio contribution acquire --help`.

## contribution patch

Apply a reviewed constrained unified text patch to acquired source.

Only regular-file text changes are supported. Existing symlinks are preserved;
creating, editing, or deleting a link, writing beneath one, or leaving a link
target dangling is refused.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.contribution-patch/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--path` | yes | — |

Inspect help: `trio contribution patch --help`.

## contribution validate

Run explicitly selected argv arrays in an offline Podman image and create a host validation seal.

Declared effect: `sandbox-execute+write-local`. Network: `network-disabled`.
Output schema: `trio.contribution-validation/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--commands` | yes | — |
| `--image` | yes | — |
| `--timeout` | no | default `60`; integer |
| `--memory-mb` | no | default `512`; integer |
| `--pids` | no | default `64`; integer |
| `--cpus` | no | default `1`; integer |

Inspect help: `trio contribution validate --help`.

## contribution plan

Prepare the exact direct/fork PR plan from sealed source; returns a separate publication plan ID.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.contribution-plan/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |
| `--branch` | yes | — |
| `--title` | yes | — |
| `--body` | yes | — |
| `--author-name` | yes | — |
| `--author-email` | yes | — |
| `--message` | no | — |
| `--mode` | no | default `direct`; choices `direct`, `fork` |
| `--fork-owner` | no | — |

Inspect help: `trio contribution plan --help`.

## contribution inspect

Inspect a publication plan and journal; supply the publication plan ID.

Declared effect: `read-local`. Network: `none`.
Output schema: `trio.contribution-inspect/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |

Inspect help: `trio contribution inspect --help`.

## contribution approve

Approve an exact publication plan digest using local approver capability.

Declared effect: `write-local`. Network: `none`.
Output schema: `trio.operation-approval/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--actor` | yes | — |
| `--digest` | yes | — |

Inspect help: `trio contribution approve --help`.

## contribution publish

Publish the approved plan through GitHub Git/PR APIs; supply the publication plan ID.

Declared effect: `write-github+write-local`. Network: `github-write`.
Output schema: `trio.contribution-journal/v1`. Explicit authorization declared: yes.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |
| `--actor` | yes | — |

Inspect help: `trio contribution publish --help`.

## contribution reconcile

Read GitHub to reconcile exact publication phases; supply the publication plan ID.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.contribution-journal/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |

Inspect help: `trio contribution reconcile --help`.

## contribution revise

Prepare a new exact publication plan for a managed contribution after patching and revalidation.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.contribution-plan/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |
| `--branch` | yes | — |
| `--title` | yes | — |
| `--body` | yes | — |
| `--author-name` | yes | — |
| `--author-email` | yes | — |
| `--message` | no | — |
| `--mode` | no | default `direct`; choices `direct`, `fork` |
| `--fork-owner` | no | — |

Inspect help: `trio contribution revise --help`.

## contribution refresh

Acquire a new upstream base and reapply the saved patch; new validation/approval are required.

Declared effect: `read-github+write-local`. Network: `github-read`.
Output schema: `trio.contribution-refresh/v1`. Explicit authorization declared: no.

| Argument | Required | Default / choices |
|---|---|---|
| `--id` | yes | — |
| `--token-env` | yes | — |
| `--base` | yes | — |
| `--base-branch` | yes | — |
| `--request-budget` | no | default `1000`; integer |

Inspect help: `trio contribution refresh --help`.

## Tranche interoperability

See the [Tranche workflow](TRANCHE_WORKFLOW.md) for the supported dependency
pin, versioned handoff contract, and complete recovery examples.

### handoff tranche

`trio handoff tranche --dataset DATASET_ID --tranche-root CHECKOUT --batch BATCH_ID --actor ACTOR [--read-token-env NAME] [--request-budget 100]`

Effect: pinned local dependency code + GitHub reads + local state writes.
Reads a separately installed supported Tranche source and report, verifies its
current generation, then captures exact revisions and creates a draft group.
No model calls or GitHub writes. Output: `trio.handoff/v1`.

### handoff prepare

`trio handoff prepare --dataset DATASET_ID --path HANDOFF_JSON --actor ACTOR`

Effect: local writes only. Validates an explicit `trio.tranche-handoff/v1` or
provider-aware `trio.tranche-handoff/v2` envelope and records repeat-safe pending work. This optional route does not
capture evidence or create a group. Output: `trio.handoff/v1`.

### handoff run

`trio handoff run --id HANDOFF_ID [--read-token-env NAME] [--request-budget 100]`

Effect: GitHub reads + local writes. The budget is 1–10,000 reads for the whole
run. Incomplete captures are retained for explicit resume; changed revisions
refuse group creation. Completed repeats return recorded observations without
new reads. Output: `trio.handoff/v1`; inspect `complete`, `outcome`, and `error`.

### handoff show

`trio handoff show --id HANDOFF_ID`

Effect: local reads only. Inspects the selected input, capture coverage,
structured references and draft group identifiers. Use `--max-bytes` for a
larger exact record when needed. Output: `trio.handoff/v1`.
