# pr-review-bot

Automated PR review bot for GitHub repositories. Polls whitelisted repos, detects new PRs, and posts review comments.

## Setup

```bash
pip install -e ".[dev]"
```

## Configuration

All config via environment variables:

| Variable | Required | Description |
|---|---|---|
| `PR_REVIEW_REPOS` | ✅ | Comma-separated `owner/repo` list (e.g. `Layr-Labs/d-inference,bstnxbt/dflash-mlx`) |
| `GITHUB_TOKEN` | ❌ | GitHub PAT (optional if `gh` CLI is authenticated) |
| `PR_REVIEW_STATE_DIR` | ❌ | Directory for state files (default: `~/.pr-review-bot`) |
| `PR_REVIEW_POLL_SECS` | ❌ | Poll interval in seconds (default: `60`) |

## Usage

### Poll for new PRs
```bash
export PR_REVIEW_REPOS="Layr-Labs/d-inference,bstnxbt/dflash-mlx"
pr-review-poll
```

Output is one JSON line per new PR — pipe into your review agent.

### Post review comments

### Listen for @mention commands
```bash
export PR_REVIEW_REPOS="owner/repo"
pr-review-listen
```

Outputs JSON lines for each new @mention command found in PR comments.

```bash
echo '{"number": 42, "body": "## Review\nLGTM!"}' | pr-review-post
```

## Testing

```bash
# Unit + integration tests
pytest -v

# E2E tests only
pytest -v -m e2e

# Skip E2E tests
pytest -v -m "not e2e"
```

## Architecture

```
src/pr_review_bot/
├── config.py          # Env-based config, dynamic repo whitelisting
├── state.py           # PR state tracking (seen/reviewed/commented/failed)
├── github_client.py   # GitHub API via gh CLI
├── poller.py          # New PR detection
├── poster.py          # Comment delivery with guarantees
└── listener.py       # PR comment monitoring with @mention dispatch

tests/
├── test_config.py     # Config loading and whitelisting
├── test_state.py      # State persistence and transitions
├── test_poller.py     # PR detection and ingestion
├── test_poster.py     # Comment posting and retry logic
├── test_listener.py   # Comment monitoring and @mention dispatch
└── test_e2e.py        # Full E2E flow tests
```


## Command-based triggering

You can trigger bot actions by mentioning `@pr-review-bot` in PR comments:

| Command | Action |
|---|---|
| `@pr-review-bot review` | Trigger review generation |
| `@pr-review-bot approve` | Fast-approve the PR |
| `@pr-review-bot re-review` | Delta review after updates |
| `@pr-review-bot merge` | Merge the PR |
| `@pr-review-bot explain` | Explain the PR changes |

Run `pr-review-listen` to poll tracked PRs for new @mention commands:
```bash
export PR_REVIEW_REPOS="owner/repo"
pr-review-listen
```

The listener tracks which comments have been processed so commands are never dispatched twice.

## Guarantees

1. **Never double-comment** — checks for existing bot comments before posting
2. **Never silently drop** — failed posts are retried on next poll cycle
3. **Assurance check** — `ensure_all_commented()` verifies comments exist on GitHub
4. **Fail-closed** — PRs stay in `failed` state until confirmed commented
