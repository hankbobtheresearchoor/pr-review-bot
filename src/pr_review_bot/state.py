"""State management — tracks which PRs have been seen / reviewed / commented."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PRRecord:
    """Tracked state for a single PR."""

    number: int
    title: str
    author: str
    status: str  # "pending_review" | "reviewed" | "commented" | "failed"
    queued_at: str = ""
    reviewed_at: str = ""
    commented_at: str = ""
    comment_id: int | None = None
    verdict: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PRRecord:
        return cls(
            number=int(data.get("number", 0)),
            title=data.get("title", ""),
            author=data.get("author", ""),
            status=data.get("status", "pending_review"),
            queued_at=data.get("queued_at", ""),
            reviewed_at=data.get("reviewed_at", ""),
            commented_at=data.get("commented_at", ""),
            comment_id=data.get("comment_id"),
            verdict=data.get("verdict", ""),
            error=data.get("error", ""),
        )


@dataclass
class RepoState:
    """Persistent state for a single repo — which PRs we've seen and their status."""

    repo: str
    state_file: Path
    prs: dict[int, PRRecord] = field(default_factory=dict)
    last_poll: str = ""
    processed_comments: dict[int, set[int]] = field(default_factory=dict)

    def mark_seen(self, number: int, title: str, author: str) -> PRRecord:
        """Mark a PR as seen + pending review. Returns the record."""
        now = _utc_now()
        rec = PRRecord(
            number=number,
            title=title,
            author=author,
            status="pending_review",
            queued_at=now,
        )
        self.prs[number] = rec
        self.last_poll = now
        return rec

    def mark_reviewed(self, number: int, verdict: str) -> None:
        """Mark a PR as reviewed (analysis done, comment not yet posted)."""
        if number in self.prs:
            self.prs[number].status = "reviewed"
            self.prs[number].reviewed_at = _utc_now()
            self.prs[number].verdict = verdict

    def mark_commented(self, number: int, comment_id: int) -> None:
        """Mark a PR as successfully commented."""
        if number in self.prs:
            self.prs[number].status = "commented"
            self.prs[number].commented_at = _utc_now()
            self.prs[number].comment_id = comment_id

    def mark_failed(self, number: int, error: str) -> None:
        """Mark a PR review as failed."""
        if number in self.prs:
            self.prs[number].status = "failed"
            self.prs[number].error = error

    def pending_reviews(self) -> list[PRRecord]:
        """Return PRs that need review comments posted."""
        return [
            r for r in self.prs.values()
            if r.status in ("pending_review", "reviewed", "failed")
        ]

    def unseen_prs(self, open_pr_numbers: list[int]) -> list[int]:
        """Return PR numbers from the open list that we haven't seen yet."""
        return [n for n in open_pr_numbers if n not in self.prs]

    def is_comment_processed(self, pr_number: int, comment_id: int) -> bool:
        """Check if a comment has already been processed."""
        return comment_id in self.processed_comments.get(pr_number, set())

    def mark_comment_processed(self, pr_number: int, comment_id: int) -> None:
        """Mark a comment as processed so it won't be re-dispatched."""
        if pr_number not in self.processed_comments:
            self.processed_comments[pr_number] = set()
        self.processed_comments[pr_number].add(comment_id)

    def save(self) -> None:
        """Persist state to disk."""
        data = {
            "repo": self.repo,
            "last_poll": self.last_poll,
            "prs": {str(k): v.to_dict() for k, v in self.prs.items()},
            "processed_comments": {str(k): list(v) for k, v in self.processed_comments.items()},
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, repo: str, state_file: Path) -> RepoState:
        """Load state from disk, or return empty state if file doesn't exist."""
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                prs = {}
                for k, v in data.get("prs", {}).items():
                    prs[int(k)] = PRRecord.from_dict(v)
                processed = {}
                for k, v in data.get("processed_comments", {}).items():
                    processed[int(k)] = set(v)
                return cls(
                    repo=repo,
                    state_file=state_file,
                    prs=prs,
                    last_poll=data.get("last_poll", ""),
                    processed_comments=processed,
                )
            except (json.JSONDecodeError, ValueError):
                pass
        return cls(repo=repo, state_file=state_file)


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
