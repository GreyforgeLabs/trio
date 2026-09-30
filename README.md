# Trio
A local-first toolkit for evidence-backed public-repository triage. The repository and command are `trio`; the import package is `trio_triage` and development distribution is `trio-triage`, avoiding the unrelated asynchronous Python Trio package. Public source and releases: https://github.com/GreyforgeLabs/trio. Package-registry publication is not part of this release.

Requires Python 3.12+ and SQLite FTS5. Core has no third-party runtime dependencies. `pip install .` then `trio commands --json` lists all effects and arguments. Start with `trio --home /tmp/example-state init --json`; all other commands require explicit state. Read-only commands do not initialize, acquire, repair, or resolve credentials.

See docs/USER_GUIDE.md for offline capture/import and team review. Writes default disabled; action transports are experimental and live validation is NOT_RUN. No live mutation, package upload, push, or release approval is claimed.

Imported evidence is untrusted data. Hash correspondence does not establish truth, current visibility, or a duplicate verdict. Review approval is separate from action authorization. Typed names are attribution, not authentication.
