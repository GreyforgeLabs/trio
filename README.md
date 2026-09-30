# Trio

Trio is Greyforge's public GitHub toolkit for contributors, maintainers,
reviewers, and their agents. It brings repository inventory, maintenance,
validated contribution workflows, evidence search, and team review together
in a local command-line application.

Start with a read-only inventory or evidence workflow, then configure the
specific actions and approvals you need. The guides below cover the current
v0.2.0 software, with examples and expected results.

## Upstream authors and acknowledgments

Trio builds on the work of these upstream authors:

- **[Erwin Francisco Macias Ghiglione (EFrMG)](https://github.com/EFrMG)** —
  author of **[triage-o-mator](https://github.com/EFrMG/triage-o-mator)**.
  Its triage workflows and selected public evidence/acquisition components
  underpin Trio's evidence and review workflows.
- **[Jeremy Dixon (Univeracity)](https://github.com/Univeracity)** —
  author of **[Reposition](https://github.com/Univeracity/reposition)**.
  Its cache, projection, indexing, search, and retrieval components underpin
  Trio's local evidence search and citations.

**Naming credit:** @ocdjeremy came up with the name **Trio**.

Thank you to both authors and their upstream contributors. Their original
copyrights and licenses are preserved. See [third-party notices](THIRD_PARTY_NOTICES.md)
for exact source versions, adaptations, and the additional Vyral attribution.

## Start here

- **New user:** [Getting started](docs/GETTING_STARTED.md) covers installation,
  a first run without GitHub credentials, and your first repository inventory.
- **Contributor:** [Contribution walkthrough](docs/CONTRIBUTIONS.md) takes a
  public issue through a patch, sandbox validation, review, and PR publication.
- **Maintainer:** [Repository operations](docs/OPERATIONS_GUIDE.md) covers
  inventory, notifications, issue management, PR actions, and recovery.
- **Reviewer or team:** [Evidence and team guide](docs/USER_GUIDE.md) covers
  capture, search, findings, review, groups, bundles, and evidence packets.
- **Looking for a feature:** [Feature guide](docs/FEATURES.md) explains every
  feature area. [Command reference](docs/COMMAND_REFERENCE.md) lists all
  62 commands, their arguments, defaults, and effects.

## What you can do today

| Your task | Tools |
|---|---|
| Inspect an account or organization | Repository/fork inventory, open PRs and issues, notifications, workflow runs, releases, snapshot comparisons |
| Maintain a repository | Issue labels/comments/close/reopen; PR ready/close/update/merge; acknowledge one notification thread |
| Contribute a fix | Public issue intake, verified source acquisition, patch application, offline sandbox validation, direct or fork PR publication |
| Investigate related work | Capture public evidence, search an index, retrieve cited source, suggest related items |
| Review together | Versioned findings, exact-digest reviews, work groups, portable event bundles, explicit conflict resolution |
| Recover after interruption | Inspect durable records and reconcile uncertain GitHub writes through reads |

## Install and try it

Python 3.12 or newer and SQLite with FTS5 support are required. Linux is the
reference environment. Podman and a preinstalled image selected by digest are
needed for contribution validation. Core installation has no mandatory Python
runtime dependencies. Git is used below to obtain the source.

```bash
git clone https://github.com/GreyforgeLabs/trio.git
cd trio
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .

export TRIO_STATE="$HOME/.local/state/trio-example"
trio --home "$TRIO_STATE" init --json
trio --home "$TRIO_STATE" doctor --json
trio commands --json
```

Choose a new state directory for the first `init`. An existing installation
uses `status` or `doctor` instead. The [quickstart](docs/GETTING_STARTED.md)
explains expected output, configuration, and the next commands.

## Before writing to GitHub

Inventory and evidence capture read GitHub. Maintenance and contribution
publication need a separately configured local policy, exact plan approval,
and fresh GitHub checks. They start disabled. The [operations guide](docs/OPERATIONS_GUIDE.md)
explains the policy fields and approval flow. Local actor names do not
authenticate people or grant GitHub permissions.

Live maintenance and contribution writes have **not been validated in a live
trial**. The release records offline tests, actual sandbox validation, and
production public read verification separately. The older `action` family
remains experimental. Release creation/upload, automatic agents, and a hosted
web interface are not implemented; see [feature boundaries](docs/FEATURES.md#current-boundaries).

## More documentation

[Product scope](docs/PRODUCT_SCOPE.md) ·
[Recovery](docs/RECOVERY.md) · [Security](SECURITY.md) ·
[Contributing to the code](CONTRIBUTING.md) ·
[Dependencies](docs/DEPENDENCIES.md) ·
[Upstream notices](THIRD_PARTY_NOTICES.md) ·
[Release verification](docs/PUBLICATION.md)

The command is `trio`, the Python import is `trio_triage`, and the distribution
is `trio-triage`. This project is separate from the asynchronous Python package
named Trio. Install from this source or its release artifacts; package-registry
publication is not part of this release. Contact: contact@greyforge.tech.
