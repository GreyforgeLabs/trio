# GitHub inventory and maintenance

[Documentation home](../README.md) · [Getting started](GETTING_STARTED.md) ·
[Command reference](COMMAND_REFERENCE.md)

Use this guide to inspect repositories and plan maintainer actions. Every
uppercase ID below is a placeholder for a value returned by your own command.
Account inventory snapshots and public evidence snapshots are different things.

Start with `trio commands --json` for the exact arguments and effects of the
`inventory` and `ops` command families. Initialize a state directory outside the
source tree. Read-only local lists and plan inspection never resolve credentials.
Explicit network commands select a token by environment-variable name; keep the
value out of command arguments and files. Inventory access may include private
repositories visible to that credential. This state remains local and separate
from public evidence, team exchange and contribution source.

## Inventory

Synchronize the selected account or organization, then inspect local lists,
repository details and drift between snapshots. Sync records its observation
time and completeness for each collection. Request/page bounds, permissions and
errors are reported as partial acquisition. Missing rows in an incomplete
collection must not be interpreted as confirmed removal. Local inventory is a
view at its recorded time, not a claim of current GitHub state.

GitHub notifications need a classic personal access token; GitHub App and
fine-grained personal access tokens do not support those endpoints. A denied
notification fetch leaves an explicitly incomplete collection. Choose the least
privilege credential that supports the operations you actually need.
[Official notification API](https://docs.github.com/en/rest/activity/notifications)

### Inventory selections and limits

```bash
trio --home "$TRIO_STATE" inventory sync --organization YOUR_ORG --repository-limit 100 --item-limit 1000 --request-budget 100 --token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" inventory list --snapshot SNAPSHOT_ID --kind notifications --limit 20 --json
trio --home "$TRIO_STATE" inventory list --snapshot SNAPSHOT_ID --kind workflow_runs --repository OWNER/REPO --limit 20 --json
trio --home "$TRIO_STATE" inventory show --snapshot SNAPSHOT_ID --repository OWNER/REPO --json
trio --home "$TRIO_STATE" inventory drift --before OLD_SNAPSHOT_ID --after NEW_SNAPSHOT_ID --json
```

Use `next_cursor` from a list as `--cursor` to continue. Per-repository kinds
(`pulls`, `issues`, `workflow_runs`, `releases`) require a repository selection.
Repository, fork, and notification lists are snapshot-level selections.
`--repository-limit` accepts 1–1,000; `--item-limit` and `--request-budget`
accept 1–10,000. These limits bound acquisition, not GitHub permission.
Notifications for an organization are filtered to its observed repositories;
partial repository acquisition also makes that notification scope partial.
Drift needs the same account identity and scope. An incomplete comparison does
not claim an item was deleted. Inventory contains observations of releases;
there is no release creation/upload command.

## Maintenance

The operations policy has a default-closed master write gate and explicit
repository/action entries. Inspect a policy before enabling it. Imported reviews,
agent proposals and evidence packet approval cannot enable this policy.

Prepare a plan for the exact repository and target with the intended issue
comment, labels or state; pull request ready, close, update or merge operation;
or selected notification thread acknowledgment. Inspect the entire plan, then
record a local approval bound to its digest. Execution rechecks the current
identity, permission, policy and target state/head. Changes invalidate approval.
Merge and branch update requests carry approved head SHA guards.
[Official pull request API](https://docs.github.com/en/rest/pulls/pulls)

An attempted write is journaled before dispatch. A successful response, definite
rejection and uncertain network result are different outcomes. Inspect operation
records and reconcile uncertain effects using reads. Do not start a new plan to
blindly replay an unresolved write. Coincidental matching text or state cannot
establish that a particular operation succeeded. Some GitHub operations are
asynchronous; acceptance is not completion.

Notification maintenance marks only the exact selected thread under its approved
repository policy. It does not mark the account's entire inbox read.

## Verification limits

Version 0.2.0 includes a real GitHub transport and offline request/recovery tests.
Live GitHub mutation verification is NOT_RUN. No credential or live account
fixture is included in this release. Local approvals are cooperative controls
within an installation, not protection against a malicious user who can edit
its filesystem. Use one designated writer for a shared workspace.


## Command examples

`TRIO_GITHUB_TOKEN` below is the name of a token environment variable you supply
locally. The command contains its name, never the credential value.

```sh
trio --home STATE init --json
trio --home STATE inventory sync --token-env TRIO_GITHUB_TOKEN --json
trio --home STATE inventory snapshots --json
trio --home STATE inventory list --snapshot SNAPSHOT_ID --kind repositories --json
trio --home STATE inventory list --snapshot SNAPSHOT_ID --kind pulls --repository example/project --json
trio --home STATE inventory drift --before OLD_SNAPSHOT --after NEW_SNAPSHOT --json
trio --home STATE ops policy --json
trio --home STATE ops policy --path REVIEWED_POLICY.json --json
trio --home STATE ops plan --token-env TRIO_GITHUB_TOKEN --operation issue-comment --repository example/project --number 42 --text 'Reviewed explanation' --json
trio --home STATE ops inspect --id PLAN_ID --json
trio --home STATE ops approve --id PLAN_ID --digest PLAN_DIGEST --actor operator --json
trio --home STATE ops execute --id PLAN_ID --actor operator --token-env TRIO_GITHUB_TOKEN --json
trio --home STATE ops reconcile --id PLAN_ID --token-env TRIO_GITHUB_TOKEN --json
trio commands --command 'ops plan' --json
```

Policy JSON uses `schema: "trio.operations-policy/v1"`, a revision string,
`identity_id`, explicit `actors` with `approver`/`publisher` roles, and
`repositories` entries with stable `repository_id` and enabled `actions`.
Maintenance also requires `maintenance_enabled`, declared `permissions` and,
for notification threads, `notifications_enabled`. Contribution writes require
`publication_enabled`. All gates start false; configure only reviewed operations.
Labels are a JSON array file and replace the target's exact label set. Merge
plans select `merge`, `squash` or `rebase` and bind the current head.

The default command catalog is a bounded summary. Select a quoted full command
with `--command` for its complete argument declaration. Increase `--max-bytes`
when you need to inspect an unusually long exact plan; a truncated summary is
not a substitute for reviewing its full intent.

## Configure a local policy

Trio uses two different configurations: evidence/review roles live in state
`config.json`; maintenance/publication roles live in `operations/policy.json`.
Use the CLI to inspect/install an explicitly reviewed operations policy.
`ops policy --path` replaces the policy, rather than merging it.

This example is **closed** and contains synthetic IDs. Save it as
`reviewed-policy.json` outside the software checkout:

```json
{
  "schema": "trio.operations-policy/v1",
  "revision": "1",
  "identity_id": 123,
  "maintenance_enabled": false,
  "publication_enabled": false,
  "notifications_enabled": false,
  "actors": {
    "reviewer": ["approver"],
    "operator": ["publisher"]
  },
  "repositories": {
    "example/project": {
      "repository_id": 456,
      "actions": ["issue-comment"]
    }
  },
  "permissions": ["issues:write"],
  "sandbox_images": []
}
```

```bash
trio --home "$TRIO_STATE" ops policy --json
trio --home "$TRIO_STATE" ops policy --path reviewed-policy.json --json
```

Replace `identity_id` with your credential's authenticated GitHub account ID,
and the repository name/ID with its verified identity. Inventory sync returns
`identity`; inventory show returns the selected repository's `id`. To authorize
maintenance in your installation, deliberately set `maintenance_enabled` to
true and allow only the intended actions/permissions. Notification operations
also need `notifications_enabled`. Configuration is a local declaration; your
actual credential must still have the necessary GitHub access.

When changing a policy, change its revision string and prepare/review new plans.
Changing policy contents invalidates old approval even if the revision label
stays the same. Separate local approver and publisher names make their roles
clear, but filesystem access can change policy; they are cooperative controls.
Do not store a GitHub token in this JSON.

## The nine maintenance operations

| `--operation` | Target arguments | Extra input | Declared permission |
|---|---|---|---|
| `notification-ack` | `--repository`, `--thread` | Exact selected notification thread | `notifications:write` |
| `issue-label` | `--repository`, `--number` | `--labels labels.json`, an array of strings replacing the label set | `issues:write` |
| `issue-comment` | `--repository`, `--number` | `--text 'Reviewed explanation'` | `issues:write` |
| `issue-close` | `--repository`, `--number` | None | `issues:write` |
| `issue-reopen` | `--repository`, `--number` | None | `issues:write` |
| `pr-ready` | `--repository`, `--number` | PR must be a draft | `pull_requests:write` |
| `pr-close` | `--repository`, `--number` | Current PR state is checked | `pull_requests:write` |
| `pr-update-branch` | `--repository`, `--number` | Approved head SHA is sent to GitHub | `contents:write` |
| `pr-merge` | `--repository`, `--number` | `--merge-method merge`, `squash`, or `rebase`; approved head SHA is sent | `contents:write` |

These strings declare local policy intent, not token scopes automatically
granted by Trio. Labels replace the complete intended label set; they do not
append automatically. Branch update can return `pending`, requiring observation
before reporting success. A merge request does not delete the branch.

## Maintainer walkthrough: comment on an issue

Use a real repository and issue selected from your inventory/evidence. The
example does not open the local policy gate for you.

```bash
trio --home "$TRIO_STATE" ops plan --operation issue-comment --repository OWNER/REPO --number 42 --text 'Reviewed explanation' --token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" ops inspect --id PLAN_ID --max-bytes 65536 --json
trio --home "$TRIO_STATE" ops approve --id PLAN_ID --digest PLAN_DIGEST --actor reviewer --json
trio --home "$TRIO_STATE" ops execute --id PLAN_ID --actor operator --token-env TRIO_GITHUB_TOKEN --json
trio --home "$TRIO_STATE" ops inspect --id PLAN_ID --json
```

Copy `id` and `digest` from the plan. Inspect the full target, text, expected
state, and policy before approval. The approval receipt is not the plan itself.
Execution uses the original plan ID and records `successful`, `pending`,
`failed`, or `uncertain` outcomes. If the target, identity, head, or policy
changes, prepare a fresh plan instead of trying to reuse old approval.

For an uncertain or pending result, inspect the same record and reconcile by
reading GitHub:

```bash
trio --home "$TRIO_STATE" ops reconcile --id PLAN_ID --token-env TRIO_GITHUB_TOKEN --json
```

Reconciliation may confirm an observed state without proving which actor caused
it. Do not resend a possibly completed write merely because a request timed out.
See [recovery](RECOVERY.md) for the durable-record workflow.
