"""Fetch a public GitHub pull request (title, description and diff)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

_PR_URL = re.compile(r"^https?://(www\.)?github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)(/.*)?$")


class GitHubError(Exception):
    pass


@dataclass
class PullRequest:
    url: str
    owner: str
    repo: str
    number: int
    title: str
    description: str
    author: str
    base: str
    head: str
    diff: str


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = _PR_URL.match(url.strip())
    if not m:
        raise GitHubError("Expected a URL like https://github.com/owner/repo/pull/123")
    return m.group(2), m.group(3), int(m.group(4))


def fetch_pr(url: str, token: str | None = None, api: str = "https://api.github.com",
             client: httpx.Client | None = None, max_chars: int = 150_000) -> PullRequest:
    owner, repo, number = parse_pr_url(url)
    headers = {"User-Agent": "multi-agent-code-review", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = f"{api}/repos/{owner}/{repo}/pulls/{number}"
    own_client = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        meta = client.get(endpoint, headers={**headers, "Accept": "application/vnd.github+json"})
        _check(meta, owner, repo, number)
        diff = client.get(endpoint, headers={**headers, "Accept": "application/vnd.github.diff"})
        _check(diff, owner, repo, number)
    except httpx.HTTPError as exc:
        raise GitHubError(f"Could not reach GitHub: {exc}") from exc
    finally:
        if own_client:
            client.close()

    if len(diff.text) > max_chars:
        raise GitHubError(f"This PR's diff is {len(diff.text):,} characters; the limit is {max_chars:,}. "
                          "Review a smaller PR or paste part of the diff.")
    data = meta.json()
    return PullRequest(
        url=url, owner=owner, repo=repo, number=number,
        title=data.get("title") or f"PR #{number}",
        description=(data.get("body") or "")[:4000],
        author=(data.get("user") or {}).get("login", ""),
        base=(data.get("base") or {}).get("ref", ""),
        head=(data.get("head") or {}).get("ref", ""),
        diff=diff.text,
    )


def _check(response: httpx.Response, owner: str, repo: str, number: int) -> None:
    if response.status_code == 404:
        raise GitHubError(f"PR {owner}/{repo}#{number} not found (private repos need GITHUB_TOKEN).")
    if response.status_code in (403, 429):
        raise GitHubError("GitHub rate limit reached. Set GITHUB_TOKEN or try again later.")
    if response.status_code >= 400:
        raise GitHubError(f"GitHub returned HTTP {response.status_code}.")
