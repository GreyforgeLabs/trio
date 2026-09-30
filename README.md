# Trio

Trio is a local GitHub operations toolkit for people and their agents. It brings
repository inventory, maintenance and public contribution workflows into one
CLI, with evidence search and collaborative triage to support decisions.

- Synchronize an account or organization and inspect repositories, forks, pull
  requests, issues, notifications, workflow runs, releases and snapshot drift.
- Preview, approve and execute repository maintenance through GitHub: issue
  comments, labels and state; pull request readiness, branch updates, closure
  and merges; selected notification acknowledgments.
- Prepare public contributions from an issue or finding, acquire exact public
  source, apply a patch, validate it in a sandbox, and publish the reviewed
  changes through a direct branch or managed fork and pull request.
- Search captured public evidence with citations, exchange proposals and reviews,
  and retain operation records for recovery after uncertain writes.

Python 3.12+ and SQLite FTS5 are required. Core Python code has no mandatory
third-party dependencies. Sandbox validation requires an installed Podman and
an explicitly selected, preinstalled container image pinned by digest. Install
with `pip install .`, initialize local state with `trio --home STATE init --json`,
and inspect `trio commands --json` for commands, arguments and effects.

See [GitHub operations](docs/OPERATIONS_GUIDE.md),
[public contribution workflow](docs/CONTRIBUTIONS.md), and
[evidence and team guide](docs/USER_GUIDE.md). The
[product scope](docs/PRODUCT_SCOPE.md) defines the public functional contract.

Write policies default closed. Every write requires an exact local plan and
approval, enabled repository/action policy, and fresh GitHub checks. Validation
and imported reviews do not authorize publication. Tokens stay transient; local
account inventory and journals belong outside the software repository.

Version 0.2.0 corrects the narrow evidence-only scope of v0.1.0. Live GitHub
mutation verification is **NOT_RUN**; offline API and sandbox qualification are
reported separately in the release. The preserved v0.1.0 tag remains available.

Public source and releases: https://github.com/GreyforgeLabs/trio. The CLI is
`trio`, import package `trio_triage`, and distribution `trio-triage`, avoiding the
unrelated asynchronous Python Trio package. Package-registry publication is not
part of this release.
