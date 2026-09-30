# Copyright (c) 2026 EFrMG. MIT; see licenses/triage-o-mator-MIT.txt.
# Adapted for TRIO: isolated fixed read contract and descriptors; omit executable auth/acquisition globals.
from datetime import datetime,timezone
from ..contracts import artifact_ref,canonical,object_name
CLOSING_QUERY = """query ClosingIssues($id: ID!, $after: String) {
  node(id: $id) {
    ... on PullRequest {
      id number url updatedAt baseRefOid headRefOid
      repository { id nameWithOwner isPrivate }
      closingIssuesReferences(first: 100, after: $after) {
        totalCount pageInfo { hasNextPage endCursor }
        nodes { id number url state updatedAt repository { id nameWithOwner isPrivate } }
      }
    }
  }
  rateLimit { remaining resetAt }
}"""

def now():
    return datetime.now(timezone.utc).isoformat()

class ReadFailure(Exception):
    def __init__(self, message, unavailable=False, http_status=None):
        super().__init__(message)
        self.unavailable = unavailable
        self.http_status = http_status

def descriptor(resource, revision, status="failed", error="not fetched yet"):
    return dict(status=status, fetched_at=now(), source=dict(transport="rest", resource=resource), revision=dict(revision), expected_count=None, received_count=None, pagination_complete=None, truncated=False, error=error, object=None)

def attach(component, data, payloads):
    payload = canonical(data) + "\n"
    ref = artifact_ref(payload)
    payloads[object_name(ref)] = payload
    component["object"] = ref

def check_scope(summary):
    """Stable repository scope matters even when the same commit appears in another fork."""
    return tuple(tuple(((summary.get(side) or {}).get("repo") or {}).get(key) for key in ("full_name", "id", "node_id")) for side in ("base", "head"))

from ..contracts import validate_item,same_item,same_repository,repository,validate_revision

def summary_identity(data, kind, number, repo):
    if not isinstance(data, dict):
        raise ValueError("summary must be an object")

    identity = dict(kind=kind, number=data.get("number"), database_id=data.get("id"), node_id=data.get("node_id"))
    validate_item(identity)
    same_item(dict(kind=kind, number=number, database_id=None, node_id=None), identity)
    if identity["database_id"] is None or identity["node_id"] is None:
        raise ValueError("GitHub summary is missing stable item IDs")

    # A redirected issue number or a PR returned through the issue endpoint must not silently enter another namespace.
    expected_url = f"https://{repo['host']}/{repo['full_name']}/{'pull' if kind == 'pr' else 'issues'}/{number}"
    if data.get("html_url") != expected_url or (kind == "issue" and "pull_request" in data):
        raise ValueError("item URL/kind changed; reconcile the namespace explicitly")

    if data.get("state") not in ("open", "closed") or "body" not in data or (data["body"] is not None and not isinstance(data["body"], str)):
        raise ValueError("summary lacks observed state/body")

    revision = dict(updated_at=data.get("updated_at"), base_sha=None, head_sha=None)
    if kind == "pr":
        base = data.get("base") or {}
        head = data.get("head") or {}
        base_repo = base.get("repo") or {}
        same_repository(repo, repository(base_repo.get("full_name"), host=repo["host"], database_id=base_repo.get("id"), node_id=base_repo.get("node_id")))
        revision.update(base_sha=base.get("sha"), head_sha=head.get("sha"))
        if type(data.get("merged")) is not bool:
            raise ValueError("PR summary lacks an explicit merged state")

    validate_revision(revision)
    if revision["updated_at"] is None or (kind == "pr" and (revision["head_sha"] is None or revision["base_sha"] is None)):
        raise ValueError("summary lacks required observation revisions")

    return identity, revision
