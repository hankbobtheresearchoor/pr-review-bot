"""PR comment listener — monitors PR comments for @mention commands."""

from __future__ import annotations

import re
import sys
from typing import Any

from .config import BotConfig, RepoConfig
from .github_client import GitHubClient
from .state import RepoState

_MENTION_RE = r'@hankbobtheresearchoor\s+(review|approve|re-review|merge|explain)(\s+.*)?'
BOT_MENTION_PATTERN = re.compile(_MENTION_RE, re.IGNORECASE)

KNOWN_COMMANDS = {"review", "approve", "re-review", "merge", "explain"}


def poll_comments(
    client: GitHubClient,
    repo_cfg: RepoConfig,
    bot_login: str = "hankbobtheresearchoor",
) -> list[dict[str, Any]]:
    """Poll tracked PRs for new comments containing @bot commands.

    Returns list of dispatch records with keys:
    repo, pr_number, comment_id, command, args, author, comment_url.
    """
    state = RepoState.load(repo_cfg.owner_repo, repo_cfg.state_file)
    dispatch: list[dict[str, Any]] = []

    for rec in state.prs.values():
        comments = client.get_issue_comments(repo_cfg.owner_repo, rec.number)
        if not comments:
            continue

        for comment in comments:
            # Skip comments from the bot itself
            if comment.get("user", {}).get("login") == bot_login:
                continue

            comment_id = comment.get("id", 0)
            # Skip already-processed comments
            if state.is_comment_processed(rec.number, comment_id):
                continue

            body = comment.get("body", "")
            match = BOT_MENTION_PATTERN.search(body)
            if not match:
                continue

            command = match.group(1).lower()
            args = (match.group(2) or "").strip()

            dispatch.append({
                "repo": repo_cfg.owner_repo,
                "pr_number": rec.number,
                "comment_id": comment_id,
                "command": command,
                "args": args,
                "author": comment.get("user", {}).get("login", "unknown"),
                "comment_url": comment.get("html_url", ""),
                "pr_title": rec.title,
                "pr_author": rec.author,
                "pr_head_sha": "",  # caller should populate via gh pr view
            })
            state.mark_comment_processed(rec.number, comment_id)

    state.save()
    return dispatch


def listen_all(config: BotConfig | None = None) -> list[dict[str, Any]]:
    """Poll all whitelisted repos for new commands. Returns combined dispatch records."""
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
    """CLI entry point — polls repos for new @mention commands and prints dispatch records."""
    try:
        config = BotConfig.from_env()
    except ValueError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    dispatch = listen_all(config)
    if not dispatch:
        return

    import json
    print(f"Found {len(dispatch)} new command(s):")
    for d in dispatch:
        print(json.dumps(d))


if __name__ == "__main__":
    main()
