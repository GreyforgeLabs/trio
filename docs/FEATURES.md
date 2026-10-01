# Feature guide

[Documentation home](../README.md) · [Getting started](GETTING_STARTED.md) ·
[Command reference](COMMAND_REFERENCE.md)

Use this page to find the right workflow for your task. It describes the
features available in v0.2.0, the commands that provide them, and where to find
step-by-step instructions.

## Find the tool for your task

| Feature | What it gives you | Commands | Guide |
|---|---|---|---|
| Setup and diagnosis | Explicit local state, configuration, FTS5 check, gate status | `init`, `status`, `doctor`, `commands` | [Quickstart](GETTING_STARTED.md) |
| Account and organization inventory | Repositories, forks, open PRs/issues, notifications, workflow runs, releases | `inventory sync`, `snapshots`, `list`, `show` | [Inventory](OPERATIONS_GUIDE.md#inventory) |
| Inventory comparisons | Changes between snapshots, with partial coverage kept explicit | `inventory drift` | [Inventory](OPERATIONS_GUIDE.md#inventory) |
| Repository maintenance | Nine explicitly selected GitHub operations | `ops policy`, `plan`, `inspect`, `approve`, `execute` | [Maintenance](OPERATIONS_GUIDE.md#maintenance) |
| Maintenance recovery | Durable dispatch records and read reconciliation | `ops inspect`, `reconcile` | [Recovery](RECOVERY.md) |
| Contribution intake | Public issue or exact local finding revision, checked for conflicts, source staleness and repository identity | `contribution intake`, `list`, `show` | [Contributions](CONTRIBUTIONS.md) |
| Verified contribution source | Exact commit/tree/blob acquisition and bounded object reads | `contribution acquire` | [Contributions](CONTRIBUTIONS.md#prepare-and-validate) |
| Patch preparation | Contained text patches against the acquired source | `contribution patch` | [Contributions](CONTRIBUTIONS.md#prepare-and-validate) |
| Sandbox validation | Explicit commands in an offline Podman container; host-created seal | `contribution validate` | [Contributions](CONTRIBUTIONS.md#prepare-and-validate) |
| PR publication | Reviewed commit/branch/PR through a direct branch or public fork | `contribution plan`, `inspect`, `approve`, `publish` | [Contributions](CONTRIBUTIONS.md#plan-and-publish) |
| Contribution recovery and updates | Reconcile writes, refresh a base, prepare an approved revision | `contribution reconcile`, `refresh`, `revise` | [Contributions](CONTRIBUTIONS.md#revise-or-refresh) |
| Public evidence datasets | Enroll a public repository; capture or import recorded public evidence | `repo add`, `repo list`, `datasets`, `capture`, `import`, `snapshots` | [Evidence](USER_GUIDE.md#capture-public-evidence) |
| Multi-item capture | Freeze a selection, acquire its members, resume its checkpoint | `corpus plan`, `corpus run` | [Corpora](USER_GUIDE.md#capture-several-items-with-a-corpus) |
| Search and citations | Ranked FTS5 or literal search over an explicit captured selection | `index build`, `index info`, `search` | [Search](USER_GUIDE.md#search-and-read-the-source) |
| Progressive retrieval | Expand a cited source and continue at a verified UTF-8 byte offset | `retrieve`, `evidence show` | [Retrieval](USER_GUIDE.md#search-and-read-the-source) |
| Related-work investigation | Title similarity leads and evidence-backed classifications | `similar`, `finding propose`, `show` | [Findings](USER_GUIDE.md#record-and-review-findings) |
| Finding review | Exact revision/digest approval, rejection, or evidence request; review withdrawal | `finding review`, `withdraw-review` | [Findings](USER_GUIDE.md#record-and-review-findings) |
| Work coordination | Member lists, assignee, notes, and draft/review/ready/archived states | `group create`, `update`, `show` | [Groups](USER_GUIDE.md#coordinate-work-with-groups) |
| Team exchange | Portable immutable event bundles or selected workspace files | `team export`, `import`, `status`, `resolve` | [Team exchange](USER_GUIDE.md#exchange-work-and-resolve-conflicts) |
| Evidence packets | Local review packets and destination-bound sharing previews | `packet`, `packet share` | [Packets](USER_GUIDE.md#prepare-an-evidence-packet) |
| Optional token budgets | Exact offline BPE accounting alongside byte limits | `search`, `retrieve` token flags | [Output budgets](USER_GUIDE.md#output-budgets-and-optional-token-accounting) |
| Local maintenance | Preview/remove disposable indexes; schema-1 migration rehearsal | `maintenance indexes`, `migrate` | [Local maintenance](USER_GUIDE.md#maintain-local-state) |
| Experimental evidence-bound actions | Separate legacy comment/close/reopen plans and journals | `action plan`, `inspect`, `authorize`, `execute`, `reconcile` | [Action status](ACTIONS.md) |

The [command reference](COMMAND_REFERENCE.md) includes every one of the 62
catalog leaves and every current argument. Maintenance verbs are choices of
`ops plan`, rather than nine additional top-level commands.

## Contributor workflow

Select a public issue → acquire an exact public base → supply a
patch → validate in the sandbox → inspect and approve a publication plan →
publish → inspect/reconcile the recorded result. Use a fork when contributing
to someone else's repository and a direct branch where you have authorized
write access. See the [complete walkthrough](CONTRIBUTIONS.md).

## Maintainer workflow

Sync inventory → select a repository and target → review a plan → approve its
exact digest → execute under a configured policy → inspect the outcome.
Inspect issue/PR evidence before making decisions. A repository name in local
policy does not grant GitHub permission. See [operations](OPERATIONS_GUIDE.md).

## Reviewer and team workflow

Capture public evidence → build an index → search and inspect citations →
record a finding → review its current digest → coordinate a work group →
preview and approve selected team or packet exports. Editing a finding makes
prior reviews stale. Imported reviews remain claimed attribution, and readiness
does not authorize a GitHub write. See [evidence and teams](USER_GUIDE.md).

## Current boundaries

- GitHub inventory can include private account metadata, which stays local.
  Evidence datasets and contribution source require public repositories.
- Core has no model client or automatic AI harness launcher. People or their
  separately chosen tools supply patches and review decisions.
- No hosted UI, built-in background scheduler, automatic merge, automatic
  branch deletion, or release creation/upload command is provided.
- Team bundles are not cryptographically signed. Local role configuration
  is cooperative and does not authenticate a person who controls the files.
- Relative source symlinks ending at tracked in-tree regular files are preserved.
  Unsafe, dangling, cyclic, directory-target, and overlong links, submodules,
  LFS pointers, unsupported entries, and unsafe paths cannot be sealed.
  Patching supports constrained regular-file text changes and preserves existing
  links; it cannot create, edit, or delete links or leave their targets dangling.
- Sandbox commands must work with a preinstalled digest-pinned image and no
  network. Trio does not install the project's dependencies during validation.
- Local-finding contribution intake requires non-conflicting, non-stale evidence
  for the selected repository; resolve conflicts or update the evidence before
  retrying. Intake grants no publication authority.
- Live maintenance and contribution write qualification remains `NOT_RUN`.
  Actual sandbox and production read checks are separate release observations.
- Index deletion is supported; automatic pruning of authoritative evidence
  is not. `migrate` currently rehearses schema 1 to schema 1 with zero changes.

## Upstream integration and credits

The public source manifest records the precise upstream paths, commits,
hashes, adaptations, and licenses. The current implementation incorporates
public evidence/acquisition components from **[triage-o-mator](https://github.com/EFrMG/triage-o-mator)**
by **[Erwin Francisco Macias Ghiglione (EFrMG)](https://github.com/EFrMG)** and cache,
projection, indexing, search, and retrieval components from
**[Reposition](https://github.com/Univeracity/reposition)** by
**[Jeremy Dixon (Univeracity)](https://github.com/Univeracity)**.
The **[Vyral](https://github.com/Univeracity/vyral)** query license notice is preserved through that public upstream
code; this does not mean Vyral's entire application was integrated.

See [source provenance](../third_party/source-manifest.json) and
[third-party notices](../THIRD_PARTY_NOTICES.md) for the original projects and
license details.

## Terminology

| Term | Meaning |
|---|---|
| Dataset | Captured public evidence for one enrolled repository identity/account namespace. |
| Snapshot | Immutable captured evidence selection; inventory also uses snapshots for account observations. |
| Corpus | A frozen multi-item evidence selection with a resumable acquisition checkpoint. |
| Index | A disposable searchable view derived from authoritative captured evidence. |
| Ref/citation | A structured reference binding captured source identity, selection, and byte boundary. |
| Finding | A versioned proposal about related items, with rationale and evidence. |
| Digest | A hash binding exact contents; changing those contents invalidates the old approval. |
| Actor | A name assigned capabilities by your local configuration. |
| Seal | Host-created validation evidence binding the patch, source tree, commands, and outcomes. |
| Plan | The exact intended operation/publication details reviewed before an action. |
| Journal | Durable phase/outcome records used to inspect or reconcile an operation. |
