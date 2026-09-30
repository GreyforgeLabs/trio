# Local evidence and team guide
`trio commands --json` is the versioned machine catalog. `--home` overrides the state root; relative roots are anchored at the selected configuration location. Default state, cache, and config use XDG conventions. `init` alone creates state. All local evidence persists outside the source tree. No authoritative-evidence pruning exists in 0.1.0.

Enroll an explicitly selected public repository or import a supported donor cache into a scope-matching dataset. Capture profiles are discussion, pr-context, pr-code, pr-comparison, and backlog. Capture reports missing/partial/not-requested components honestly. A corpus plan freezes captured membership; run/resume never adds new members. Index build explicitly creates a disposable view. Search uses ranked FTS5 or explicitly literal mode, returns citations to authoritative immutable bytes, and fails on changed progress. Retrieve expands a selected boundary. Deleted indexes do not invalidate source refs.

Roles are explicitly configured per installation; start with a synthetic JSON config listing reader/contributor/reviewer/maintainer capabilities, installation_id, and disabled writes. No name is authenticated by being typed. Findings use immutable revisions and exact digest reviews. Edits stale old reviews. Groups coordinate draft/needs_review/ready/archived work; readiness grants no authority. Team export previews selected decision events, explicit approval writes a bundle, import validates and is idempotent. Imported reviews are claimed; local reviewers can review exact imported proposals. Competing heads require explicit maintainer resolution naming every predecessor.

Packets default local. Share previews the exact screened payload and destination; approve its digest to export. Team notes require separate consent and are withheld by default. Source citations do not imply secret-free content. Sensitive output fails without printing rejected values. JSON max-bytes counts the entire compact response including newline. Text display escapes terminal controls and differs in formatting.

Actions are experimental, default disabled, and require separate local publisher designation/roles, exact enabled operation, live identity/state/scope checks, exact local authorization and a sole writer. Only comment, explained closure and explained reopen are supported; merged PR reopen refuses. Unknown outcomes require read reconciliation and cannot be blindly retried. One designated publisher installation serves a team; review installations never gain authority from imported events.

Offline import into a new dataset: initialize empty state, provide a reviewed recorded-public scope JSON (format_version1, github.com host, positive stable repository_id, full_name, visibility public, observed_at timezone timestamp, profile null or explicit account namespace), then `trio --home STATE import --scope SCOPE.json --path CACHE --json`. Existing `--dataset` imports require an exactly matching source identity. No offline scope declaration claims current visibility.

Optional tokens require the separately hash-locked extra and a caller-selected official BPE file: `--tokenizer-encoding cl100k_base --tokenizer-asset ASSET --max-tokens LIMIT`. No query downloads encodings or estimates tokens. CLI token settings below128 and byte settings below1024 are invalid invocations because a complete machine error envelope requires a minimum floor; accepted dual budgets measure the same final response/newline. JSON errors use a fixed generic envelope.

Team event files use explicitly selected workspace destinations, user-managed Git only, and exact destination-bound approval digests. Signed exchange is not implemented; all imported attribution stays claimed. Source scope privacy suspension blocks shares. Long completed local mutation responses return bounded summaries with record identifiers rather than implying the already-completed effect was refused.

A bounded live inventory is explicit: `trio capture --dataset DATASET --inventory --limit 100 --request-budget 100 --json` (use spaces between flag and value). It records completeness/truncation and freezes observed membership. Alternatively select already-captured observations with `trio corpus plan --dataset DATASET --snapshot SNAPSHOT1 --snapshot SNAPSHOT2 --profile discussion --json`. Changed identity/revision combinations refuse instead of selecting an arbitrary winner. Run the returned corpus explicitly to capture selected members, then explicitly build a new index for its changed checkpoint.

`trio corpus run` resumes unfinished members and retries partial or failed captures,
prioritizing the least-attempted members so small request budgets can make progress.
Completed members keep their recorded observations; completion does not establish
current visibility or freshness. A completed run with no remaining work makes no
requests and preserves its checkpoint. To request new observations for every frozen
member, use `trio corpus run --refresh` once, then ordinary `corpus run` to continue
after a budget stop or interruption. Outstanding refresh work is recorded as `gaps`
with `refresh requested`; older immutable snapshots remain inspectable until replaced
in corpus progress. Repeating `--refresh` requests another full refresh.

The typical offline review sequence is import -> index build -> search -> retrieve selected reference -> finding propose -> finding review exact digest -> team export preview -> approve/export -> team import -> packet local or approved share. Findings/groups use explicit synthetic/public attribution from the init config; names in source text and imported bundles never grant those roles. A comment or explained close/reopen action requires a separately prepared exact live plan and local publisher authorization; production execution remains disabled until a disposable public live test is separately authorized.

To continue reading a selected source, pass the returned fragment's
`continuation.byte_offset` to `trio retrieve --ref REF.json --byte-offset OFFSET`
and reuse its `continuation.window` with `--window`. The offset is measured in
UTF-8 bytes from the cited source boundary, not from the previous excerpt.
Keep the verified reference for that source; invalid offsets and offsets inside
a UTF-8 character are refused. An omitted offset retains the initial behavior.
