# AGENTS.md — pr-review-bot

## Project Overview
Automated PR review bot for GitHub repositories. Polls whitelisted repos, detects new PRs, and posts review comments with strict delivery guarantees.

## Repository Structure
```
src/pr_review_bot/
├── __init__.py       # Package version
├── config.py         # Env-based config, dynamic repo whitelisting
├── state.py          # PR state machine (seen → reviewed → commented / failed)
├── github_client.py  # GitHub API via gh CLI + REST
├── poller.py         # New PR detection across repos
├── poster.py         # Comment delivery with dedup + retry
└── listener.py       # PR comment monitoring with @mention command dispatch

tests/
├── conftest.py       # Shared fixtures (mock client, temp state dir)
├── test_config.py    # Config loading, whitelisting, env parsing
├── test_state.py     # State machine transitions, persistence, corruption recovery
├── test_poller.py    # PR detection, dedup, multi-repo, error resilience
├── test_poster.py    # Comment posting, retry, dedup, assurance checks
├── test_listener.py  # Comment monitoring, @mention dispatch, state persistence
└── test_e2e.py       # Full E2E flow tests (PR detect → analyze → comment)

.github/workflows/
└── ci.yml            # CI: lint + test on Python 3.11/3.12/3.13
```

## Configuration (all via env)
| Variable | Required | Description |
|---|---|---|
| `PR_REVIEW_REPOS` | ✅ | Comma-separated `owner/repo` list |
| `GITHUB_TOKEN` | ❌ | GitHub PAT (optional if `gh` CLI is authenticated) |
| `PR_REVIEW_STATE_DIR` | ❌ | State file directory (default: `~/.pr-review-bot`) |
| `PR_REVIEW_POLL_SECS` | ❌ | Poll interval in seconds (default: 60) |

## Development Setup
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests
```bash
pytest -v                    # All tests
pytest -v -m e2e             # E2E flow tests only
pytest -v -m "not e2e"      # Unit + integration only
pytest --cov                 # With coverage
```

## Architecture Decisions

### State Machine
Every PR goes through: `seen → pending_review → commented`
- On comment post failure → `failed` → retried on next cycle
- PRs are **never** marked `commented` until the comment is confirmed via API
- `ensure_all_commented()` cross-checks local state against GitHub to detect deleted comments


### Comment Listener
-  polls tracked PRs for new comments containing  mentions
- Supported commands: , , , , 
- Already-processed comments are tracked and never re-dispatched
- Bot's own comments are automatically skipped
- Use  CLI to poll for new @mention commands


### Delivery Guarantees
1. **Never double-comment** — `has_bot_comment()` checks GitHub before posting
2. **Never silently drop** — failed posts stay in `failed` state and are retried
3. **Fail-closed** — a PR only leaves `pending_review` when the comment ID is confirmed

### Dynamic Whitelisting
- `PR_REVIEW_REPOS` parsed on every `BotConfig.from_env()` call
- Adding a repo: set env var, next poll cycle picks it up
- Removing a repo: set env var, state file persists but no new polls
- Each repo gets its own state file: `{state_dir}/{owner}_{repo}_state.json`

## Code Style
- Python 3.11+ with type hints
- `ruff` for linting (configured in pyproject.toml)
- Dataclasses for config and state records
- `unittest.mock.MagicMock` for test doubles — no external test servers

## Key Gotchas
- The `gh` CLI must be authenticated for `github_client.py` to work (or set `GITHUB_TOKEN`)
- State files are per-repo JSON — safe for concurrent reads but NOT concurrent writes
- `PRRecord.status` transitions are one-way except `failed → pending_review` for retries
- E2E tests use `@pytest.mark.e2e` — run them separately or all together
