# GitHub inventory and maintenance

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
