# Getting started

[Documentation home](../README.md) · [Feature guide](FEATURES.md) ·
[Command reference](COMMAND_REFERENCE.md)

This guide takes you from installation to your first local workspace and
repository inventory. Start without credentials to check your installation,
then choose the workflow that matches your task.

## 1. Install

Use Python 3.12 or newer with SQLite FTS5. Linux is the reference environment.
You need Git for the clone below. Contribution validation also needs Podman;
inventory, search, and local review do not.

```bash
git clone https://github.com/GreyforgeLabs/trio.git
cd trio
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
trio commands --json
```

The last command should print one JSON object with `schema: "trio.commands/v1"`
and a `leaves` list. It works before state is initialized and does not contact
GitHub. There is no interactive wizard; commands return results directly.

## 2. Create a local workspace

Keep state outside the source checkout. It contains your captured evidence,
account inventory, plans, and journals.

```bash
export TRIO_STATE="$HOME/.local/state/trio-example"
trio --home "$TRIO_STATE" init --json
trio --home "$TRIO_STATE" status --json
trio --home "$TRIO_STATE" doctor --json
trio --home "$TRIO_STATE" datasets --json
```

Use a new, empty directory for `init`; it returns `state_version: 1` and
`writes_enabled: false`. `doctor` should report `initialized: true` and
`fts5: true`. An empty `datasets` result is normal before enrolling evidence.
These commands need no GitHub token. Reusing a nonempty directory with `init`
returns `ALREADY_INITIALIZED`; inspect that installation with `status` instead.

`--home` chooses the state directory for each command. Without it, state uses
the XDG state location. Relative values resolve against the selected config
location, so an absolute path is easier to understand. See [configuration](USER_GUIDE.md#configuration-and-local-roles).

## 3. Understand command output

Use `--json` for scripts and agents; omit it for text display. A successful
command normally exits 0. Exit 1 means attention is needed, for example partial
inventory or pending work. Exit 3 is a refusal, and exit 4 means a transport
failure or an uncertain/failed write. Read the result before retrying.

```bash
trio commands --command 'inventory sync' --json
trio commands --command 'contribution validate' --json
trio inventory sync --help
```

The default catalog is a short summary. Use `--command` for the arguments of
one command. The [complete reference](COMMAND_REFERENCE.md) also explains
defaults, required choices, effects, output limits, and exit codes.

## 4. Supply a token for GitHub reads

Token selection is explicit. Inventory, operations, and contributions use
`--token-env`; evidence enrollment/capture use `--read-token-env`. Both flags
take an environment-variable **name**, never the token itself.

In Bash, enter a token without putting it in shell history:

```bash
read -r -s -p 'GitHub token: ' TRIO_GITHUB_TOKEN
printf '\n'
export TRIO_GITHUB_TOKEN
```

Use a credential with access appropriate to your chosen repositories. The
notification endpoints require a classic personal access token; a credential
unsupported by one collection leaves that collection incomplete. Read access
does not grant permission to publish. Trio does not automatically run `gh auth`
or discover a token from unrelated files.

## 5. Inspect your repository inventory

```bash
trio --home "$TRIO_STATE" inventory sync --token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" inventory snapshots --json
```

Copy the `snapshot` value from the sync result and replace `SNAPSHOT_ID` below:

```bash
trio --home "$TRIO_STATE" inventory list --snapshot SNAPSHOT_ID --kind repositories --json
trio --home "$TRIO_STATE" inventory show --snapshot SNAPSHOT_ID --repository OWNER/REPO --json
trio --home "$TRIO_STATE" inventory list --snapshot SNAPSHOT_ID --kind pulls --repository OWNER/REPO --json
```

`OWNER/REPO` is a repository name from the inventory. A list is limited by
default; pass its returned `next_cursor` as `--cursor` to continue. Check
`complete`, `error`, and the observation time: a saved view may be partial or
stale. This inventory can include private repositories visible to the token;
keep its state local.

## 6. Choose your workflow

| You want to… | Continue with |
|---|---|
| Investigate an issue or PR | [Capture, search, and retrieve evidence](USER_GUIDE.md#capture-public-evidence) |
| Prepare a fix for a public project | [Contribution walkthrough](CONTRIBUTIONS.md) |
| Comment, label, close, update, or merge | [Maintainer walkthrough and policy](OPERATIONS_GUIDE.md) |
| Review a finding or exchange work | [Findings and team workflows](USER_GUIDE.md#record-and-review-findings) |
| Inspect an interrupted operation | [Recovery guide](RECOVERY.md) |

All uppercase identifiers in the guides are placeholders. Use the IDs and
digests returned by your own commands; do not copy another installation's IDs.
Quoted actor names such as `reviewer` are local roles you configure explicitly.

## Common first-run problems

| Result | What to do |
|---|---|
| `trio: command not found` | Activate the virtual environment used for installation. |
| `NOT_INITIALIZED` | Check `--home`, then initialize a new empty state directory. |
| `ALREADY_INITIALIZED` | Use `status` on the existing directory; choose a different path for a new workspace. |
| `SCOPE_DENIED` during initialization | Use a state directory outside the checkout and avoid symlinked paths. |
| `fts5: false` | Use a Python installation whose SQLite includes FTS5 before building search indexes. |
| Token or permission error | Check the selected variable name and repository access; inspect the stable JSON error code. |
| Partial inventory | Inspect component errors and request limits; do not interpret missing records as deletions. |
| `GATE_CLOSED` | Review the local operations policy and intended action; approval alone does not open a gate. |
| `BUDGET_TOO_SMALL` | Increase `--max-bytes`, or request a smaller selection. |

Troubleshooting does not require deleting the database or enabling GitHub writes.

## Frequently asked questions

**Which package should I install?** Use this repository or its release artifacts.
The distribution is `trio-triage`, the Python import is `trio_triage`, and the
command is `trio`. The unrelated asynchronous Python package named `trio` does
not provide this toolkit.

**Can I use it without an AI subscription?** Yes. Trio has no built-in model
client. You can supply patches and review decisions yourself, or use your chosen
tool. No agent starts automatically.

**What works offline?** Once evidence or inventory is saved, you can inspect
local views, search indexed evidence, retrieve citations, review findings,
coordinate groups, and prepare bundles or packets. Synchronization, acquisition,
remote reconciliation, and publication need GitHub access. Sandbox validation
runs offline with an image and tools already installed locally.

**Will installing or initializing it change my repositories?** No. Installation
sets up the CLI; initialization creates local state. GitHub writes require the
specific configured policy, exact approval, suitable credentials, and fresh
precondition checks described in the workflow guides.

**Is there a browser interface?** The current interface is the CLI. Use `--json`
for scripts and agents, or omit it for text output.

**Can I reuse my existing ForgeHub configuration or database?** Use Trio's own
initialization and guides. ForgeHub has a different CLI and state format;
`migrate` is not a converter between them.
