"""GitHub API client — wraps gh CLI and REST API for PR operations."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class PRInfo:
    """Basic metadata for a pull request."""

    number: int
    title: str
    author: str
    branch: str
    url: str
    created_at: str
    updated_at: str
    head_sha: str
    state: str


class GitHubClient:
    """GitHub API client using gh CLI. Stateless — all auth comes from gh auth."""

    def __init__(self, github_token: str | None = None) -> None:
        self._token = github_token

    def _gh(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
        """Run a gh CLI command."""
        cmd = ["gh"] + args
        env = None
        if self._token:
            import os
            env = {**os.environ, "GH_TOKEN": self._token}
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )

    def _gh_api(self, endpoint: str, jq: str | None = None) -> str | None:
        """Call gh api and return stdout, or None on failure."""
        cmd = ["gh", "api", endpoint]
        if jq:
            cmd += ["--jq", jq]
        env = None
        if self._token:
            import os
            env = {**os.environ, "GH_TOKEN": self._token}
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def list_open_prs(self, repo: str) -> list[PRInfo]:
        """List all open PRs for a repo."""
        output = self._gh_api(f"repos/{repo}/pulls?state=open&per_page=100")
        if not output:
            return []
        try:
            raw = json.loads(output)
        except json.JSONDecodeError:
            return []
        return [
            PRInfo(
                number=p["number"],
                title=p.get("title", ""),
                author=p.get("user", {}).get("login", "unknown"),
                branch=p.get("head", {}).get("ref", ""),
                url=p.get("html_url", ""),
                created_at=p.get("created_at", ""),
                updated_at=p.get("updated_at", ""),
                head_sha=p.get("head", {}).get("sha", ""),
                state=p.get("state", "open"),
            )
            for p in raw
        ]

    def get_pr_diff(self, repo: str, pr_number: int) -> str | None:
        """Fetch the diff for a PR."""
        result = self._gh(["pr", "diff", str(pr_number), "--repo", repo], timeout=60)
        if result.returncode != 0:
            return None
        return result.stdout

    def get_pr_files(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Get the list of changed files for a PR."""
        output = self._gh_api(f"repos/{repo}/pulls/{pr_number}/files")
        if not output:
            return []
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []


    def get_issue_comments(self, repo: str, issue_number: int) -> list[dict[str, Any]]:
        """Get issue comments for a PR (PRs are issues with code). Handles pagination."""
        all_comments = []
        page = 1
        while True:
            endpoint = f"repos/{repo}/issues/{issue_number}/comments?per_page=100&page={page}"
            output = self._gh_api(endpoint)
            if not output:
                break
            try:
                page_comments = json.loads(output)
                if not page_comments:
                    break
                all_comments.extend(page_comments)
                page += 1
            except json.JSONDecodeError:
                break
        return all_comments

    def post_comment(self, repo: str, pr_number: int, body: str) -> int | None:
        """Post a top-level comment on a PR. Returns the comment ID, or None on failure."""
        result = self._gh(
            ["pr", "comment", str(pr_number), "--repo", repo, "--body", body],
            timeout=60,
        )
        if result.returncode != 0:
            return None
        # gh pr comment outputs the comment URL; extract ID from it
        output = result.stdout.strip()
        # Format: https://github.com/OWNER/REPO/pull/NUM#issuecomment-COMMENTID
        if "issuecomment-" in output:
            try:
                return int(output.split("issuecomment-")[-1].split()[0].rstrip("/"))
            except (ValueError, IndexError):
                pass
        return None

    def get_comments(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        """Get issue comments on a PR."""
        output = self._gh_api(f"repos/{repo}/issues/{pr_number}/comments")
        if not output:
            return []
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    def has_bot_comment(self, repo: str, pr_number: int, bot_login: str) -> bool:
        """Check if the bot has already commented on a PR."""
        comments = self.get_comments(repo, pr_number)
        return any(c.get("user", {}).get("login") == bot_login for c in comments)

    def post_review(
        self,
        repo: str,
        pr_number: int,
        head_sha: str,
        body: str,
        event: str = "COMMENT",
        inline_comments: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Submit a formal PR review with optional inline comments."""
        import os

        payload: dict[str, Any] = {
            "commit_id": head_sha,
            "event": event,
            "body": body,
        }
        if inline_comments:
            payload["comments"] = inline_comments

        token = self._token or os.environ.get("GITHUB_TOKEN", "")
        cmd = [
            "curl", "-s", "-X", "POST",
            "-H", f"Authorization: token {token}",
            "-H", "Accept: application/vnd.github+json",
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews",
            "-d", json.dumps(payload),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return False
        try:
            resp = json.loads(result.stdout)
            return resp.get("id") is not None
        except json.JSONDecodeError:
            return False
