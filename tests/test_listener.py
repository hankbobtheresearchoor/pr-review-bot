"""Tests for the PR comment listener module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from pr_review_bot.config import RepoConfig
from pr_review_bot.github_client import GitHubClient
from pr_review_bot.listener import BOT_MENTION_PATTERN, poll_comments
from pr_review_bot.state import RepoState


class TestBotMentionPattern:
    def test_match_review(self):
        assert BOT_MENTION_PATTERN.search("@hankbobtheresearchoor review")
        assert BOT_MENTION_PATTERN.search("@hankbobtheresearchoor review this PR please")

    def test_match_approve(self):
        assert BOT_MENTION_PATTERN.search("@hankbobtheresearchoor approve")

    def test_match_re_review(self):
        assert BOT_MENTION_PATTERN.search("@hankbobtheresearchoor re-review")

    def test_match_merge(self):
        assert BOT_MENTION_PATTERN.search("@hankbobtheresearchoor merge")

    def test_match_explain(self):
        assert BOT_MENTION_PATTERN.search("@hankbobtheresearchoor explain")

    def test_no_match_without_mention(self):
        assert not BOT_MENTION_PATTERN.search("please review this PR")
        assert not BOT_MENTION_PATTERN.search("@other-bot review")

    def test_extract_command_and_args(self):
        m = BOT_MENTION_PATTERN.search("@hankbobtheresearchoor review this specific PR")
        assert m.group(1) == "review"
        assert m.group(2) == " this specific PR"

    def test_args_stripped_in_dispatch(self):
        m = BOT_MENTION_PATTERN.search("@hankbobtheresearchoor review this specific PR")
        assert m.group(1) == "review"
        assert m.group(2) == " this specific PR"

    def test_case_insensitive(self):
        assert BOT_MENTION_PATTERN.search("@PR-REVIEW-BOT REVIEW")

    def test_no_match_unknown_command(self):
        assert not BOT_MENTION_PATTERN.search("@hankbobtheresearchoor unknown-command")


class TestPollComments:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_file = Path(self.tmpdir) / "test-state.json"
        self.repo_cfg = RepoConfig(
            owner_repo="test-owner/test-repo",
            state_file=self.state_file,
        )

    def test_returns_empty_when_no_tracked_prs(self):
        client = _mock_client()
        results = poll_comments(client, self.repo_cfg)
        assert results == []

    def test_ignores_comments_without_mention(self):
        client = _mock_client(comments=[
            {"id": 1, "user": {"login": "alice"}, "body": "just a normal comment"}
        ])
        _seed_state(self.state_file, "test-owner/test-repo", pr_numbers=[42])
        results = poll_comments(client, self.repo_cfg)
        assert results == []

    def test_dispatches_review_command(self):
        client = _mock_client(comments=[
            {"id": 1, "user": {"login": "alice"}, "body": "@hankbobtheresearchoor review", "html_url": "https://github.com/test-owner/test-repo/pull/42#issuecomment-1"}
        ])
        _seed_state(self.state_file, "test-owner/test-repo", pr_numbers=[42])
        results = poll_comments(client, self.repo_cfg)
        assert len(results) == 1
        assert results[0]["command"] == "review"
        assert results[0]["pr_number"] == 42
        assert results[0]["author"] == "alice"

    def test_skips_already_processed_comments(self):
        client = _mock_client(comments=[
            {"id": 1, "user": {"login": "alice"}, "body": "@hankbobtheresearchoor review"}
        ])
        _seed_state(self.state_file, "test-owner/test-repo", pr_numbers=[42])
        # First pass — should dispatch
        results = poll_comments(client, self.repo_cfg)
        assert len(results) == 1
        # Second pass — should skip
        results = poll_comments(client, self.repo_cfg)
        assert results == []

    def test_skips_bot_own_comments(self):
        client = _mock_client(comments=[
            {"id": 1, "user": {"login": "hankbobtheresearchoor"}, "body": "@hankbobtheresearchoor review"}
        ])
        _seed_state(self.state_file, "test-owner/test-repo", pr_numbers=[42])
        results = poll_comments(client, self.repo_cfg)
        assert results == []

    def test_handles_multiple_commands_across_prs(self):
        client = _mock_client(comments=[
            {"id": 1, "user": {"login": "alice"}, "body": "@hankbobtheresearchoor review"},
            {"id": 2, "user": {"login": "bob"}, "body": "LGTM"},
            {"id": 3, "user": {"login": "carol"}, "body": "@hankbobtheresearchoor approve"},
        ])
        _seed_state(self.state_file, "test-owner/test-repo", pr_numbers=[42, 43])
        results = poll_comments(client, self.repo_cfg)
        assert len(results) == 4
        commands = {r["command"] for r in results}
        assert commands == {"review", "approve"}

    def test_save_and_load_processed_comments(self):
        """Verify processed_comments survives save/load roundtrip."""
        client = _mock_client(comments=[
            {"id": 1, "user": {"login": "alice"}, "body": "@hankbobtheresearchoor review"}
        ])
        _seed_state(self.state_file, "test-owner/test-repo", pr_numbers=[42])
        # Process the comment
        poll_comments(client, self.repo_cfg)
        # Reload state and verify comment is still marked processed
        state2 = RepoState.load("test-owner/test-repo", self.state_file)
        assert state2.is_comment_processed(42, 1)


def _mock_client(comments=None):
    client = MagicMock(spec=GitHubClient)
    client.get_issue_comments.return_value = comments or []
    return client


def _seed_state(state_file, repo, pr_numbers):
    state = RepoState(repo=repo, state_file=state_file)
    for n in pr_numbers:
        state.mark_seen(n, f"PR #{n}", "author")
    state.save()
