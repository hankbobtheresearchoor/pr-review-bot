"""PR comment listener — monitors PR comments for @mention commands.

Polls issue + review comments for @mentions, and auto-responds to review feedback on the bot's own PRs.
Checks review comments on pending_review PRs in batches of 10 per cycle.
"""

from __future__ import annotations

import json
import re
import sys
import time
from typing import Any

from .config import BotConfig, RepoConfig
from .github_client import GitHubClient
from .state import RepoState

_MENTION_RE = r'@hankbobtheresearchoor\b'
BOT_MENTION_PATTERN = re.compile(_MENTION_RE, re.IGNORECASE)

_COMMAND_RE = r'@hankbobtheresearchoor\s+(review|approve|re-review|merge|explain)(\s+.*)?'
COMMAND_PATTERN = re.compile(_COMMAND_RE, re.IGNORECASE)

_MAX_PR_REVIEW_CHECK = 10  # Max PRs to check for review comments per cycle


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def poll_comments(
    client: GitHubClient,
    repo_cfg: RepoConfig,
    bot_login: str = "hankbobtheresearchoor",
) -> list[dict[str, Any]]:
    """Poll a repo for new @mentions. Fast — O(1) issue + O(10) review checks."""
    state = RepoState.load(repo_cfg.owner_repo, repo_cfg.state_file)
    since = state.last_listen or None
    now = _utc_now()
    dispatch: list[dict[str, Any]] = []

    # 1. Issue comments — one global API call per repo (fast)
    comments = client.get_repo_comments_since(repo_cfg.owner_repo, since=since) or []
    mentioned_prs: set[int] = set()
    for comment in comments:
        if comment.get("user", {}).get("login") == bot_login:
            continue
        comment_id = comment.get("id", 0)
        pr_number = _extract_issue_number(comment.get("issue_url", ""))
        if pr_number is None or state.is_comment_processed(pr_number, comment_id):
            continue
        body = comment.get("body", "")
        if not BOT_MENTION_PATTERN.search(body):
            continue
        # Skip comments from known automated bots (vercel, dependabot, etc.)
        commenter = comment.get("user", {}).get("login", "")
        if commenter.endswith("[bot]") or commenter in ("dependabot", "renovate"):
            continue

        # Don't auto-review bot-authored PRs (but explicit @mentions still work)
        pr_rec = state.prs.get(pr_number)
        is_mention = BOT_MENTION_PATTERN.search(body)
        if pr_rec and pr_rec.author == bot_login and not is_mention:
            state.mark_comment_processed(pr_number, comment_id)
            continue
        dispatch.extend(_build_dispatch(repo_cfg.owner_repo, state, comment, pr_number, body))
        state.mark_comment_processed(pr_number, comment_id)
        mentioned_prs.add(pr_number)

    # 2. Review comments — batch of N pending_review PRs (prevents hang)
    pending_prs = sorted(
        [r for r in state.prs.values() if r.status == "pending_review"],
        key=lambda r: r.number, reverse=True  # newest first
    )
    for rec in pending_prs[:_MAX_PR_REVIEW_CHECK]:
        rcomments = client.get_pr_review_comments_since(
            repo_cfg.owner_repo, rec.number, since=since
        ) or []
        for comment in rcomments:
            if comment.get("user", {}).get("login") == bot_login:
                continue
            comment_id = comment.get("id", 0)
            if state.is_comment_processed(rec.number, comment_id):
                continue
            body = comment.get("body", "")
            # Skip known bots
            commenter = comment.get("user", {}).get("login", "")
            if commenter.endswith("[bot]") or commenter in ("dependabot", "renovate"):
                continue

            # Respond to @mentions OR review comments on bot-authored PRs (from others)
            is_mention = BOT_MENTION_PATTERN.search(body)
            is_own_pr = (rec.author == bot_login and 
                        comment.get("user", {}).get("login") != bot_login)
            if not is_mention and not is_own_pr:
                continue
            drec = _build_dispatch(repo_cfg.owner_repo, state, comment, rec.number, body)[0]
            drec["review_path"] = comment.get("path", "")
            drec["review_line"] = comment.get("line", 0)
            dispatch.append(drec)
            state.mark_comment_processed(rec.number, comment_id)

    state.last_listen = now
    state.save()
    return dispatch


def _build_dispatch(
    repo: str, state: RepoState, comment: dict, pr_number: int, body: str
) -> list[dict[str, Any]]:
    cmd_match = COMMAND_PATTERN.search(body)
    if cmd_match:
        command = cmd_match.group(1).lower()
        args = (cmd_match.group(2) or "").strip()
    else:
        command = "review"
        args = body[:300]
    pr_rec = state.prs.get(pr_number)
    return [{
        "repo": repo,
        "pr_number": pr_number,
        "comment_id": comment.get("id", 0),
        "command": command,
        "args": args,
        "author": comment.get("user", {}).get("login", "unknown"),
        "comment_url": comment.get("html_url", ""),
        "pr_title": pr_rec.title if pr_rec else f"PR #{pr_number}",
        "pr_author": pr_rec.author if pr_rec else "unknown",
        "pr_head_sha": "",
    }]


def _extract_issue_number(issue_url: str) -> int | None:
    if not issue_url:
        return None
    parts = issue_url.rstrip("/").split("/")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return None


def listen_all(config: BotConfig | None = None) -> list[dict[str, Any]]:
    if config is None:
        config = BotConfig.from_env()
    client = GitHubClient(github_token=config.github_token)
    all_dispatch: list[dict[str, Any]] = []
    for repo_cfg in config.repos:
        try:
            dispatch = poll_comments(client, repo_cfg)
            all_dispatch.extend(dispatch)
        except Exception as e:
            print(f"Error listening to {repo_cfg.owner_repo}: {e}", file=sys.stderr)
    return all_dispatch


def main() -> None:
    try:
        config = BotConfig.from_env()
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)
    dispatch = listen_all(config)
    if not dispatch:
        return
    for d in dispatch:
        print(json.dumps(d))


if __name__ == "__main__":
    main()
