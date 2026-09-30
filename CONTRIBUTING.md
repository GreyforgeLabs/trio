# Contributing to Trio

[Documentation home](README.md) · [Feature guide](docs/FEATURES.md) ·
[Command reference](docs/COMMAND_REFERENCE.md)

For fixing a public project *using* Trio, start with the
[contribution walkthrough](docs/CONTRIBUTIONS.md). This page is for improving
Trio's own code and documentation.

## Get a development checkout

Use Python 3.12 or newer with SQLite FTS5 support:

```bash
git clone https://github.com/GreyforgeLabs/trio.git
cd trio
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
trio commands --json
```

Keep runtime state outside the checkout. Use public sources and synthetic
fixtures in changes and tests; do not include private repositories, live
caches, credentials, workstation paths, or assistant histories.

## Make a reviewable change

Explain the concrete problem and resulting behavior. Include reproduction
steps for a bug, or an example of the workflow a feature enables. Keep unrelated
changes separate. Update the relevant guide and command catalog when behavior,
arguments, effects, or defaults change. Keep descriptions consistent with the
[product scope](docs/PRODUCT_SCOPE.md) and the behavior users can actually run.

Preserve donor provenance, licenses, legitimate human credits, and upstream
notices. Newly authored contributions are Apache-2.0. Choose the public Git
author identity explicitly; do not add AI author/co-author trailers or assistant
bylines.

## Check the change

The existing synthetic test suite runs without live GitHub credentials:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v
```

For documentation, check examples against command help and the versioned
catalog, confirm links and anchors work, and explain expected results. Do not
claim a live GitHub action was tested when only a fixture was exercised.

New public files must be included in the explicit source/artifact allowlists
and source manifest under `third_party/`. CI stages only that reviewed file
selection and runs provenance and secret-scanner checks. See
[publication](docs/PUBLICATION.md) for the scanner and release gates; a green
CI result does not itself approve an official release.

## Send a pull request

Describe what changed, why, the checks actually performed, and any remaining
limitations. Use the repository's issue template for bugs, and
[SECURITY.md](SECURITY.md) for security reports. Exact official release approvals
remain separate from source contributions.
