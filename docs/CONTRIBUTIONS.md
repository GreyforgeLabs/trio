# Public contribution workflow

The `contribution` command family takes an issue or a local finding through
public source acquisition, patch validation, exact publication approval and
pull request publication. `trio commands --json` provides the versioned machine
catalog. There is no built-in model or automatic agent launcher; a person or
separately chosen tool supplies the patch and proposed PR text.

## Prepare and validate

Intake selects a public GitHub repository and issue or records a local finding.
Acquire resolves a precise base commit and obtains a complete public source tree.
Acquire and refresh have an explicit `--request-budget` (default 1000) covering
bounded Git object reads; an exhausted budget cannot produce a valid source seal.
Truncated trees, private repositories, unsupported symlinks/submodules and unsafe
paths must not become a valid source bundle. A caller-provided patch applies only
to contained regular files. Runtime state and Git administrative files do not
belong in contribution source.

Select a preinstalled sandbox image by immutable digest and explicit validation
commands appropriate to the project. Validation requires Podman. It runs with
network disabled, limited resources, no host home or credentials, no SSH/Git
helpers or container socket, and only the chosen public source. Do not run
repository tests or instructions directly on the host. Container output is
bounded and untrusted; a message saying tests passed is not a validation seal.

The host creates a seal only after actual command outcomes and exact resulting
source are verified. It binds repository/base, patch, resulting tree, validation
commands and results. Editing source or commands requires revalidation. A seal
cannot be created by importing team events or accepting a claimed test result.
A failing or incomplete validation does not authorize publication.

## Plan and publish

Prepare the precise destination, base, branch, title and body from a sealed
contribution. Inspect them, enable the required local repository/action policy,
and approve the exact plan digest. Choose a direct branch when authorized in the
upstream repository or a managed public fork when contributing externally.
Fork and branch identities remain explicit in the plan.

Publication uses GitHub's Git database and pull request APIs. It creates the
reviewed blobs/tree/commit, creates the designated branch without force,
and creates the pull request. Existing unrelated branches are not overwritten.
The transport verifies current identities, public visibility, permissions and
base/head facts before effects. It must preserve unrelated files in the complete
base tree. [GitHub Git database API](https://docs.github.com/en/rest/git)

Fork creation may be asynchronous. Publication records phases and returns
pending or uncertain outcomes when it cannot prove completion. Read-only
reconciliation adopts only effects matching the exact repository, branch,
commit/tree and PR identity. It does not blindly repeat requests after a timeout
or infer success from matching PR body text.

## Revise or refresh

Revise explicitly selects the managed contribution and its expected PR/head;
prepare the new patch, validate it and obtain a fresh publication approval.
Unrelated branch changes invalidate the old authority. Refresh acquires the new
base and requires a patch that applies and passes validation against it; old
seals and approvals cannot be reused across base changes.

## Verification limits

Offline API fixtures cover publication behavior. The release qualification
records the actual sandbox exercise separately. Live GitHub mutation
verification is NOT_RUN; the release does not claim a public fork or PR was
created in a trial. Tokens and local account inventory are never contribution
source or release inputs.


## Command examples

These placeholders require your selected public repository, exact SHA and local
policy. `commands.json` is an explicit JSON array of argv arrays, for example
`[["python", "-m", "unittest", "discover", "-s", "tests"]]` for a project that
supports that command. Select commands after inspecting the public project.

```sh
trio --home STATE contribution intake --repository example/project --issue 42 --token-env TRIO_GITHUB_TOKEN --json
trio --home STATE contribution acquire --id CONTRIBUTION_ID --base BASE_SHA --base-branch main --token-env TRIO_GITHUB_TOKEN --json
trio --home STATE contribution patch --id CONTRIBUTION_ID --path change.patch --json
trio --home STATE contribution validate --id CONTRIBUTION_ID --commands commands.json --image APPROVED_IMAGE_DIGEST --json
trio --home STATE contribution plan --id CONTRIBUTION_ID --branch contribution/fix --title 'Fix the reported behavior' --body pr-body.md --author-name 'Your Name' --author-email your-email@example.com --mode fork --fork-owner YOUR_LOGIN --token-env TRIO_GITHUB_TOKEN --json
trio --home STATE contribution inspect --id PUBLICATION_PLAN_ID --json
trio --home STATE contribution approve --id PUBLICATION_PLAN_ID --digest PLAN_DIGEST --actor operator --json
trio --home STATE contribution publish --id PUBLICATION_PLAN_ID --actor operator --token-env TRIO_GITHUB_TOKEN --json
trio --home STATE contribution reconcile --id PUBLICATION_PLAN_ID --token-env TRIO_GITHUB_TOKEN --json
trio commands --command 'contribution revise' --json
trio commands --command 'contribution refresh' --json
```

The policy must explicitly allow `contribution-publish` for the upstream stable
repository ID, the selected `mode` and `fork_owner` when using a fork. Declare
`contents:write` and `pull_requests:write`, approved sandbox image digests and
local approver/publisher roles. Enabling these local declarations does not grant
GitHub permissions; the live credential and repository must also allow the write.
Author name and email are supplied explicitly; Trio does not add an AI co-author
or assistant byline.

Refresh reacquires the explicitly selected base and reapplies the saved patch;
resolve conflicts before revalidation. Revise requires a managed prior PR and
creates a fresh exact plan. Both workflows need a new validation seal and approval.
