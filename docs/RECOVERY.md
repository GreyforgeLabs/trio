# Recovery and migration

[Documentation home](../README.md) · [Getting started](GETTING_STARTED.md) ·
[Command reference](COMMAND_REFERENCE.md)

An interrupted command is not always safe to repeat. Start by identifying
whether it only read GitHub, changed local data, or dispatched a GitHub write.
Keep the state directory and the command's returned IDs so you can inspect the
recorded outcome.

## An interrupted GitHub operation

A timeout after a write may mean GitHub accepted it but the reply was lost.
Trio records intent before dispatch. Reconciliation reads GitHub to establish
what happened; it does not replay an uncertain request.

For repository maintenance, use the operation ID returned by `ops plan`:

```bash
trio ops inspect --id OPERATION_ID --json
trio ops reconcile --id OPERATION_ID --token-env TRIO_GITHUB_TOKEN --json
```

For contribution publication, use the publication plan ID, which is different
from the contribution intake ID:

```bash
trio contribution inspect --id PUBLICATION_PLAN_ID --json
trio contribution reconcile --id PUBLICATION_PLAN_ID --token-env TRIO_GITHUB_TOKEN --json
```

Include the same `--home` used for the original command. Inspect the phases and
outcomes in the response. A comment followed by a state transition is two
effects: one can succeed while the other remains incomplete. Fork creation can
also remain pending while GitHub prepares the fork. Do not infer completion
from a similar comment or PR title.

Do not dispatch the same uncertain write from another installation: local
replay protection does not coordinate separate state directories. Publisher
handover refuses while unresolved operations remain. See the
[operations guide](OPERATIONS_GUIDE.md) and
[contribution guide](CONTRIBUTIONS.md) for the relevant plan and approval flow.

## Local interruption and partial results

| Situation | What is retained | Next step |
|---|---|---|
| Inventory sync is partial | Saved observations and explicit coverage/errors | Inspect the component error and limits; missing records do not prove deletion. Perform a new sync when ready. |
| A corpus run stops | Frozen membership and an acquisition checkpoint | Resume the same corpus ID with `corpus run`; do not create a new selection merely to continue it. |
| Capture stops before publication | Complete but possibly unreferenced objects | Inspect snapshots/checkpoints before assuming a complete capture. Manifests do not intentionally refer to incomplete bytes. |
| Index build fails | The previous complete index view | Correct the reported problem and build again; index replacement publishes atomically. |
| Team import fails validation | No partially inserted event batch | Correct the bundle; validated insertion is transactional. Reimporting the same valid events is idempotent. |
| A packet export stops | The previous complete destination file | Check the returned result; atomic replacement publishes only complete files. |
| A finding changes after review | Old revision and review history | Review the new revision/digest; the old approval does not approve the new contents. |
| Patch, base, or validation commands change | Previous contribution records | Acquire/refresh as needed, validate again, and approve a new exact publication plan. |

## Back up authoritative state

Keep the entire selected state directory, including evidence, the database,
and journals. Keep your local configuration separately if it is outside that
directory. Make a consistent filesystem backup while no Trio command is writing.
Account inventory can contain private metadata; a backup is not a team bundle
or a public artifact. Do not remove journals to clear an uncertain operation.

## Schema migration

```bash
trio migrate --json
trio migrate --apply --json
```

The first command rehearses on a disposable copy. `--apply` retains a
checksum-verified backup. Currently the only supported schema is version 1,
and migration from version 1 to itself makes zero schema changes. It is not a
ForgeHub database converter. Future and foreign schemas refuse; rollback
cannot lower a schema version or erase action journals.

## Remove disposable indexes

```bash
trio maintenance indexes --json
trio maintenance indexes --id INDEX_ID --json
trio maintenance indexes --id INDEX_ID --apply --json
```

The first two commands preview selection. Only `--apply` removes selected
indexes. Captured evidence is retained, and evidence pruning is not automatic.
You can rebuild an index from its captured selection; see
[local maintenance](USER_GUIDE.md#maintain-local-state).
