# Configuration

## Backend environment

Copy `backend/.env.example` to `backend/.env`. Every value has a sane default for local
development except the LLM and GitHub credentials.

### LLM (provider-agnostic, OpenAI-compatible)

Anything that speaks `POST /chat/completions` works — Groq, OpenAI, Together, a local
server.

| Variable | Notes |
|---|---|
| `OPENAI_BASE_URL` | e.g. `https://api.groq.com/openai/v1` |
| `OPENAI_API_KEY` | provider key |
| `OPENAI_MODEL` | default `openai/gpt-oss-120b` |
| `GROQ_API_KEY_1..3` | extra keys, rotated automatically on `429` |

For offline development point `OPENAI_BASE_URL` at any local OpenAI-compatible proxy and set
a placeholder key.

### GitHub

| Variable | Notes |
|---|---|
| `GITHUB_TOKEN` | **required** for the PR bot; needs `repo` + `read:org` to read diffs, issues and to post reviews |
| `GITHUB_WEBHOOK_SECRET` | **required**; the webhook is fail-closed without it |

### Storage

| Variable | Notes |
|---|---|
| `BUGLENS_DB` | engine state file (idempotency, findings, feedback, index). Defaults next to the package. |
| `DATABASE_URL` | app database for analytics/history; SQLite by default, PostgreSQL in production |
| `REDIS_URL` | optional. Without it, rate limits and budgets run in memory / no-op |

### Auth and origins

| Variable | Notes |
|---|---|
| `ADMIN_API_KEY` | enables `/api/v1/engine/stats`; unset means that endpoint returns `503` |
| `EXTENSION_SHARED_SECRET` | if unset, the IDE endpoints are unauthenticated (fine for a single-user self-host) |
| `ALLOWED_ORIGINS` | comma-separated CORS origins |
| `ENVIRONMENT` | `production` turns config warnings into hard startup failures |

### Tuning (optional)

| Variable | Default | Effect |
|---|---|---|
| `BUGLENS_MAX_CONCURRENT_REVIEWS` | `8` | reviews running at once in the process |
| `BUGLENS_SQLITE_POOL` | `4` | SQLite connections kept for the engine store |
| `BUGLENS_SQLITE_BUSY_MS` | `5000` | how long a writer waits for the write lock |
| `BUGLENS_LLM_MAX_CONNECTIONS` | `32` | shared HTTP connection pool for LLM calls |
| `BUGLENS_VERIFY_CONCURRENCY` | `4` | model-gate calls in flight per review |
| `BUGLENS_FETCH_CONCURRENCY` | `8` | concurrent GitHub file fetches per review |
| `BUGLENS_STALE_RUN_MIN` | `30` | minutes before an unfinished run may be retried |
| `BUGLENS_SWEEP_HOURS` | `24` | interval between cache/index sweeps |
| `BUGLENS_COST_PER_1M_IN` | unset | $ per 1M input tokens — enables the cost figure in the review footer |
| `BUGLENS_COST_PER_1M_OUT` | unset | $ per 1M output tokens (used with the above) |

The footer always reports engine calls, failed calls, tokens (when the provider returns them)
and wall-clock; a **dollar figure appears only when both cost variables are set**, so the bot
never publishes a price it invented.

## Running it

```bash
cd backend
uv venv && uv pip install -r requirements.txt
.venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

On Linux/macOS use `.venv/bin/python`. The engine needs no Redis, no queue and no vector
database: SQLite in WAL mode is enough for the state it keeps. See
[operations.md](operations.md) for what that means under load, and what to change first if
you outgrow it.

## VS Code extension

Open Settings (`Ctrl+,`) and search **buglens**.

| Setting | Default | Description |
|---|---|---|
| `buglens.apiUrl` | hosted backend | Point at your own server |
| `buglens.reviewOnSave` | `false` | Review automatically on save |
| `buglens.showInlineHighlights` | `true` | Coloured underlines on problem lines |

The extension identifies itself with a key compiled into the bundle. That is deliberately not
a strong secret — it stops casual scripted abuse, not a determined attacker — so on a
self-hosted instance set `EXTENSION_SHARED_SECRET` only if you also rebuild the extension with
a matching key, or leave it unset.

## Repo rules

`.buglens.yml` at the repo root, plus optional nested files for subtrees. Custom lenses go in
`.buglens/lenses/*.md`. Both are documented in [engine.md](engine.md#repo-rules-buglensyml).

Two keys govern the re-review loop: `max_rounds` (default `10`) stops the bot on a PR that has
been reviewed that many times, and `converge_rounds` (default `3`) switches to *new-code-only*
reviews after that many rounds (deterministic — a file is only re-reviewed if its diff actually
changed). Set either to `0` to disable it.

## Supported languages

Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby, PHP, Swift, Dart, Kotlin,
Scala, HTML, CSS, SCSS, SQL, Bash, Shell, YAML, JSON, Elixir, Haskell, Clojure, R, Julia, Lua
and more. The diff parser is language-agnostic; the code graph uses Python's `ast` and a
regex fallback elsewhere.
