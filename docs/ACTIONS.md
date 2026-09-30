# Preserved evidence-bound actions

This document covers the original `action` family. Version 0.2.0 provides real
GitHub maintenance and contribution transports in separate `ops` and
`contribution` workflows; see OPERATIONS_GUIDE.md and CONTRIBUTIONS.md.

The subsystem prepares exact local plans for comments, explained closure, and
explained reopening. Writes default to disabled. Merge, labels, pushes, forks,
arbitrary endpoints, and unattended bulk execution are unsupported.

One mutation orchestrator and a deterministic fake transport are supplied for
qualification. A production GitHub write adapter and authorized live trial are
**NOT_RUN**. This candidate does not advertise live-validated actions. The CLI
can preview and authorize experimental plans; it refuses live execution until
an explicitly selected production transport is available.

The Python service API in trio_triage.actions is plan, inspect, authorize,
execute, reconcile, and publisher_ready. A plan binds an enrolled stable target,
operation, exact explanation, expected issue state or PR state/head/merged
facts, local policy revision, and an optional exact finding digest. The caller
obtains facts through the selected read transport for a current live preview.
Offline previews bind recorded or synthetic facts and do not claim current
visibility. Execution rechecks remote identity, public visibility, state, head,
publisher identity, and write permissions immediately before effects.

The installation must match the designated local publisher_id; the actor needs
the locally configured publisher role. Both writes_enabled and the individual
enabled_actions entry are required. Imported reviews and claimed names never
create action authorization. Local authorization binds plan digest, actor, and
installation. Changing text, target, decision, policy, or preconditions requires
a new preview and authorization.

Action-bound findings are checked against the local ledger. A conflict, changed
finding, absent local approval, rejected review, withdrawn approval, corrupt
reference, newer material source revision, or privacy suspension blocks
execution. Outgoing token/key patterns and control characters block a plan.
Generic screening is not proof that sensitive content is absent. A detected
public-to-private transition records local sharing suspension.

Intent and each uncertain dispatch marker are atomically flushed before the
transport may mutate anything. One nonblocking local publisher lock coordinates
attempts. Explained closure/reopening posts the exact approved comment before
the state change. A comment may change update timestamps; later checks preserve
identity/state/head facts rather than requiring an unchanged timestamp.

Each step records not_sent, not_requested, succeeded, failed, or unknown.
A rejection is failed only when the transport guarantees nondelivery.
Disconnects before or after acknowledgement remain unknown. Comment success
and failed or uncertain state changes stay separate. A completed operation ID
returns its recorded outcome. Reconciliation performs reads only and requires
affirmative operation-linked observations, not a coincidentally matching state.
Unknown attempts never replay automatically. A new operation ID cannot bypass
an unresolved attempt or authorize repeating the same confirmed comment.
Partial attempts require a new exact plan for independently reviewed intent.

Before publisher handover, publisher_ready must report no unresolved attempts.
Independent installations do not share this lock or replay ledger. Configure
one designated publisher per workspace; others remain review-only. Cooperative
local controls do not claim distributed exactly-once execution or protection
from malicious filesystem access.

The injected transport exposes identity, current_target, comment, set_state,
and read-only observe. Credentials stay transient within a future transport,
never in plans, journals, arguments, retained headers, errors, or team files.
Transport exception text is never serialized.

Current GitHub documentation was verified: comments need Issues(write) or
Pull requests(write); issue updates need Issues(write) or Pull requests(write);
PR updates need Pull requests(write). The service conservatively requires the
matching capability. Use separately selected repository-scoped credentials
only after enabling a tested adapter. See
[comments](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment),
[issues](https://docs.github.com/en/rest/issues/issues#update-an-issue), and
[pull requests](https://docs.github.com/en/rest/pulls/pulls#update-a-pull-request).
