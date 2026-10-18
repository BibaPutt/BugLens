"""GitHub REST client for the v2 pipeline.

Fixes the v1 client's worst behaviours:

* **pagination**, v1 fetched only the first 30 files (GitHub's default page);
* **file content**, v1 only ever had the patch, so it reviewed a diff blob;
* **inline reviews**, v1 posted one issue-level comment per file; v2 posts one
  review with comments pinned to real added lines;
* **honest errors**, every call checks status and raises instead of logging
  success on a 403 (v1 printed "✅ posted" after a failed POST).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
DEFAULT_TIMEOUT = 30.0
MAX_FILES = 300
MAX_TREE = 4000
MAX_PAGES = 20
ISSUE_BODY_CHARS = 4000


class GitHubError(RuntimeError):
    pass


def token() -> str | None:
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


def configured() -> bool:
    return bool(token())


def _headers() -> dict:
    tok = token()
    if not tok:
        raise GitHubError("GITHUB_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@dataclass
class PRInfo:
    owner: str
    repo: str
    number: int
    base_sha: str
    head_sha: str
    draft: bool
    title: str
    body: str
    author: str
    state: str


_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    """One process-wide keep-alive pool for GitHub too.

    A review makes ~20-30 API calls; a fresh client per call meant a fresh TCP+TLS
    handshake for every one of them.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
            follow_redirects=True,
        )
    return _client


async def aclose() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def _request(method: str, url: str, *, params=None, json=None, accept=None) -> httpx.Response:
    headers = _headers()
    if accept:
        headers["Accept"] = accept
    return await _http().request(method, url, headers=headers, params=params, json=json)


async def get_pr(owner: str, repo: str, number: int) -> PRInfo:
    resp = await _request("GET", f"{API}/repos/{owner}/{repo}/pulls/{number}")
    if resp.status_code != 200:
        raise GitHubError(f"get_pr {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return PRInfo(
        owner=owner, repo=repo, number=number,
        base_sha=data["base"]["sha"], head_sha=data["head"]["sha"],
        draft=bool(data.get("draft")), title=data.get("title", ""),
        body=data.get("body") or "", author=(data.get("user") or {}).get("login", ""),
        state=data.get("state", "open"),
    )


async def get_pr_files(owner: str, repo: str, number: int) -> list[dict]:
    """All changed files, following pagination (v1 stopped at 30)."""
    files: list[dict] = []
    page = 1
    while len(files) < MAX_FILES:
        resp = await _request(
            "GET", f"{API}/repos/{owner}/{repo}/pulls/{number}/files",
            params={"per_page": 100, "page": page},
        )
        if resp.status_code != 200:
            raise GitHubError(f"get_pr_files {resp.status_code}: {resp.text[:200]}")
        batch = resp.json()
        if not batch:
            break
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return files[:MAX_FILES]


async def get_file_content(owner: str, repo: str, path: str, ref: str) -> str | None:
    """Raw file body at a ref, or None if it does not exist / is too large."""
    resp = await _request(
        "GET", f"{API}/repos/{owner}/{repo}/contents/{path}",
        params={"ref": ref}, accept="application/vnd.github.raw",
    )
    if resp.status_code != 200:
        return None
    text = resp.text
    return text if len(text) <= 200_000 else text[:200_000]


async def get_repo_tree(owner: str, repo: str, ref: str) -> list[str]:
    """Recursive blob paths at a ref, capped, for the lightweight codebase index."""
    resp = await _request(
        "GET", f"{API}/repos/{owner}/{repo}/git/trees/{ref}",
        params={"recursive": "1"},
    )
    if resp.status_code != 200:
        return []
    tree = resp.json().get("tree", [])
    return [t["path"] for t in tree if t.get("type") == "blob"][:MAX_TREE]


async def post_review(owner: str, repo: str, number: int, commit_id: str, body: str,
                      comments: list[dict], event: str = "COMMENT") -> dict:
    """One consolidated review with inline comments.

    ``comments`` items: {"path", "line", "side": "RIGHT", "body"}.
    ``event`` is COMMENT by default; REQUEST_CHANGES only when a repo opted in.
    Raises GitHubError on failure so callers never report false success.
    """
    if event not in ("COMMENT", "REQUEST_CHANGES"):
        event = "COMMENT"
    payload = {"commit_id": commit_id, "body": body, "event": event, "comments": comments}
    resp = await _request("POST", f"{API}/repos/{owner}/{repo}/pulls/{number}/reviews", json=payload)
    if resp.status_code not in (200, 201):
        raise GitHubError(f"post_review {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def post_issue_comment(owner: str, repo: str, number: int, body: str) -> dict:
    resp = await _request("POST", f"{API}/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})
    if resp.status_code not in (200, 201):
        raise GitHubError(f"post_issue_comment {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def _find_marked_comment(owner: str, repo: str, number: int, marker: str) -> dict | None:
    """Page through every issue comment looking for our marker.

    The old version read only the first 100 comments, so on a busy PR it never found the
    previous BugLens comment and posted a duplicate on every push.
    """
    page = 1
    while page <= MAX_PAGES:
        resp = await _request("GET", f"{API}/repos/{owner}/{repo}/issues/{number}/comments",
                              params={"per_page": 100, "page": page})
        if resp.status_code != 200:
            return None
        batch = resp.json()
        if not batch:
            return None
        for comment in batch:
            if marker in (comment.get("body") or ""):
                return comment
        if len(batch) < 100:
            return None
        page += 1
    return None


async def upsert_marked_comment(owner: str, repo: str, number: int, marker: str, body: str) -> dict:
    """Update our previous summary comment in place (identified by a hidden marker)."""
    existing = await _find_marked_comment(owner, repo, number, marker)
    if existing:
        upd = await _request("PATCH", f"{API}/repos/{owner}/{repo}/issues/comments/{existing['id']}",
                             json={"body": body})
        if upd.status_code == 200:
            return upd.json()
    return await post_issue_comment(owner, repo, number, body)


async def create_check_run(owner: str, repo: str, head_sha: str, name: str,
                           conclusion: str, title: str, summary: str) -> dict:
    payload = {
        "name": name, "head_sha": head_sha, "status": "completed", "conclusion": conclusion,
        "output": {"title": title[:255], "summary": summary[:65000]},
    }
    resp = await _request("POST", f"{API}/repos/{owner}/{repo}/check-runs", json=payload)
    if resp.status_code not in (200, 201):
        raise GitHubError(f"create_check_run {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ── issues, tickets, history (context, not review) ─────────────────────────────
_CLOSING_ISSUES_QUERY = """
query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      closingIssuesReferences(first:10){
        nodes{ number title url body repository{ nameWithOwner } }
      }
    }
  }
}
"""


async def graphql(query: str, variables: dict) -> dict:
    """One GraphQL call (cheaper than many REST round-trips for linked issues/history)."""
    resp = await _request("POST", GRAPHQL, json={"query": query, "variables": variables})
    if resp.status_code != 200:
        raise GitHubError(f"graphql {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("errors"):
        raise GitHubError(f"graphql errors: {str(data['errors'])[:200]}")
    return data.get("data") or {}


async def closing_issues(owner: str, repo: str, number: int) -> list[dict]:
    """Issues a PR will close, per GitHub itself (default-branch aware).

    Returns [{number,title,url,body,repo}]. Empty on any failure, spec context is a
    bonus, never a reason to fail a review.
    """
    try:
        data = await graphql(_CLOSING_ISSUES_QUERY, {"owner": owner, "name": repo, "number": number})
    except Exception:
        return []
    pr = ((data.get("repository") or {}).get("pullRequest") or {})
    nodes = ((pr.get("closingIssuesReferences") or {}).get("nodes")) or []
    out = []
    for n in nodes:
        out.append({
            "number": n.get("number"),
            "title": n.get("title") or "",
            "url": n.get("url") or "",
            "body": (n.get("body") or "")[:ISSUE_BODY_CHARS],
            "repo": ((n.get("repository") or {}).get("nameWithOwner")) or f"{owner}/{repo}",
        })
    return out


async def get_issue(owner: str, repo: str, number: int) -> dict | None:
    resp = await _request("GET", f"{API}/repos/{owner}/{repo}/issues/{number}")
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {"number": data.get("number"), "title": data.get("title") or "",
            "body": (data.get("body") or "")[:ISSUE_BODY_CHARS],
            "state": data.get("state"), "labels": [l.get("name") for l in data.get("labels") or []]}


async def get_pr_commit_messages(owner: str, repo: str, number: int, limit: int = 30) -> list[str]:
    resp = await _request("GET", f"{API}/repos/{owner}/{repo}/pulls/{number}/commits",
                          params={"per_page": min(limit, 100)})
    if resp.status_code != 200:
        return []
    return [(c.get("commit") or {}).get("message") or "" for c in resp.json()][:limit]


async def get_review_comments(owner: str, repo: str, number: int, limit: int = 100) -> list[dict]:
    """Comments on a PR (both review/inline and issue-level) for prior-conversation recall."""
    out: list[dict] = []
    resp = await _request("GET", f"{API}/repos/{owner}/{repo}/pulls/{number}/comments",
                          params={"per_page": min(limit, 100)})
    if resp.status_code == 200:
        for c in resp.json():
            out.append({"id": c.get("id"), "body": (c.get("body") or "")[:600],
                        "path": c.get("path") or "", "user": (c.get("user") or {}).get("login", "")})
    return out


async def get_commits_for_path(owner: str, repo: str, path: str, limit: int = 10) -> list[str]:
    resp = await _request("GET", f"{API}/repos/{owner}/{repo}/commits",
                          params={"path": path, "per_page": min(limit, 100)})
    if resp.status_code != 200:
        return []
    return [c.get("sha") for c in resp.json()][:limit]


async def pulls_for_commit(owner: str, repo: str, sha: str) -> list[dict]:
    resp = await _request("GET", f"{API}/repos/{owner}/{repo}/commits/{sha}/pulls")
    if resp.status_code != 200:
        return []
    return [{"number": p.get("number"), "title": p.get("title") or "",
             "merged_at": p.get("merged_at")} for p in resp.json()]
