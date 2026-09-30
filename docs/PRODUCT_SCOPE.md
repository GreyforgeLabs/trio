# Trio public GitHub operations

Trio is a public, installable GitHub operations toolkit for people and their
agents. Its purpose is to manage repositories and prepare and publish public
contributions. Evidence search and collaborative review support those workflows.
This scope supersedes the functional exclusions in the original v0.1.0
integration contract. It does not change the public-source provenance boundary.

## Required workflows

1. **Repository inventory.** Synchronize an authenticated account or selected
   organization using the GitHub API. Store a local inventory of repositories,
   forks, open pull requests, issues, notifications, workflow runs and releases.
   Provide bounded JSON lists, repository details, freshness timestamps, partial
   acquisition reporting and drift between snapshots. A failed or partial sync
   must not present absent records as deletions. Account data is local runtime
   state and is never distributed with the software.
2. **Repository maintenance.** Provide concrete preview plans for notification
   acknowledgments; issue label, comment, close and reopen operations; and pull
   request ready, close, update-branch and merge operations. Use a real GitHub
   transport. Default gates are closed. Execution requires an explicitly enabled
   repository/action policy, a local approval bound to the exact plan, current
   authenticated identity and permissions, and current target preconditions.
   Journal attempted, successful, failed and uncertain operations. A timeout
   after sending a write is uncertain: reconcile by reading remote state and do
   not blindly repeat a potentially successful operation.
3. **Public contribution preparation.** Intake a public repository issue or a
   local finding into a contribution queue. Acquire only public GitHub source
   at an exact commit. Accept a user-supplied patch, constrain its paths, and
   apply and validate it in an isolated environment. Treat repository code and
   instructions as untrusted. There must be a functioning sandbox backend for
   explicitly requested validation, with no credentials or host home mounts,
   network disabled and bounded time/resources. Record actual commands, outcomes,
   base and resulting commit/tree/diff hashes. A validation seal binds those
   bytes, never a claimed success supplied by imported evidence.
4. **Public contribution publication.** Build exact reviewable publication plans
   from sealed validated patches, including repository, base/head, branch, title
   and body. Support authorized direct repository branches and managed public
   forks. Execution requires the local publication gate and approval, current
   public visibility, identity/permissions and base/head checks. Publish the
   reviewed tree through the real GitHub API and create the pull request. Support
   explicit revisions, base refresh/revalidation and uncertain-operation
   recovery without duplicate pull requests or overwriting unrelated branches.

## Interface and boundaries

The `trio` CLI is the product interface. Preserve the existing evidence and team
commands. Expose command discovery, effect descriptions and useful JSON errors.
No model subscription, automatic agent launcher or hosted service is required.
Credentials are resolved only for explicit network operations, are never stored
in plans or journals, and are redacted from errors. Local state files are private.
GitHub object text is data, not instructions or authorization.

No undocumented owner's private source, configuration, account inventory,
implementation, tests or Git history may enter this public implementation.
New code is independently authored using this public behavioral contract,
the already published Trio source and official GitHub, Git, Python and container
documentation. Existing legitimate licenses and provenance records remain.

## Acceptance

Ship usable end-to-end commands, not only interfaces or unavailable-adapter
placeholders. Test real request construction against an offline HTTP fixture and
test uncertain writes, stale approvals, changed identities, denied permissions,
path attacks and validation failures. Existing evidence tests remain green.
Exercise sandbox patch validation against an innocuous local test repository.
Build and install both wheel and source distribution in a clean environment.
Independent technical and confidentiality reviews must assess this scope as well
as the code and release artifacts. Keep live GitHub mutation verification labeled
NOT_RUN unless an authorized trial actually occurred. Preserve the public v0.1.0
release and publish the corrected version as v0.2.0 to GreyforgeLabs/trio.

Official API references:
- https://docs.github.com/en/rest/repos/repos
- https://docs.github.com/en/rest/issues/issues
- https://docs.github.com/en/rest/pulls/pulls
- https://docs.github.com/en/rest/activity/notifications
- https://docs.github.com/en/rest/git
- https://docs.github.com/en/rest/actions/workflow-runs
- https://docs.github.com/en/graphql/reference/mutations


## Review acceptance details

Pagination must honor validated GitHub next-page links and endpoint limits.
Partial pages, resource bounds, denied permissions and changing selection must
remain explicitly incomplete. Notification acknowledgments bind one exact
thread and its repository/action policy; never use account-wide mark-read.

Merge and update requests carry approved head SHA preconditions. Empty success
responses and asynchronous acceptance need endpoint-specific handling; malformed
or unconfirmed post-dispatch responses remain uncertain. Reconciliation reports
observed postconditions separately from proof that this operation caused them.

Acquisition requires a complete tree; truncated recursive trees do not qualify.
Both existing source and patch paths reject links, submodules, Git administrative
paths and traversal. Validate the entire resulting tree, preserving unchanged
files and modes. The trusted host creates the seal after a real bounded sandbox
run; sandbox output or files cannot supply release authority.

Publication records its fork/blob/tree/commit/ref/PR/revision phases before
writes. Branch creation is nonforcing and never adopts an unrelated branch.
Recovery can adopt only exact repository/identity/base/head/tree/commit matches,
with unknown attribution left unknown. Tokens never cross untrusted redirect or
pagination origins. Private account inventory is not public contribution source.

A CLI-level offline HTTP matrix must exercise every maintenance verb and direct
and fork contribution preparation/publication/revision/base refresh/recovery.
Actual sandbox validation is a separate observed qualification gate.
