# AGENTS.md — BugLens (read me first, every session)

Working memory for autonomous agents. **If you are an agent picking this up: read this
file, then `ITERATION.md`, then continue the checklist below. Do not ask the user to
re-explain.**

## What this is
BugLens is a code-review product with three surfaces:
1. **PR bot** — a GitHub webhook that reviews pull requests and posts a consolidated review.
2. **VS Code extension** (`vscode-extension/`) — reviews the current file in the IDE.
3. **Dashboard** (`BugAnalytics.html`) + FastAPI backend (`backend/`).

Repo: `github.com/Vansh940/BugLens`. Local branch for all v2 work: **`enhance/v2-engine`**.
**Never push to `main`.** Commit locally only, and only when the user asks.

## Ground rules (locked by the user)
- **Provider-agnostic LLM.** OpenAI-compatible API. Default provider Groq; `OPENAI_BASE_URL`
  can point at a local proxy (e.g. `http://127.0.0.1:4096/v1`) for dev.
- **Never block a PR.** Post `event=COMMENT` always (no `REQUEST_CHANGES`), never fail a build.
- **One consolidated review per PR** (inline comments + one summary), never a comment storm.
- **Evidence or it doesn't ship.** Every finding must be anchored to an added line and must
  survive the verify gate (`buglens/verify.py`). No proof → dropped.
- **Idempotent.** Re-running a webhook for the same commit must not double-post.
- **No new required services.** Must run on SQLite + no Redis for local dev/tests.

## Architecture (v2 engine: `backend/buglens/`)
| file | job |
|---|---|
| `diff.py` | parse unified diff, map to **new-file** line numbers, join added text, fingerprints |
| `severity.py` | severity taxonomy (blocker/high/medium/low/info), ranking, comment budget |
| `rules.py` | load `.buglens.yml` (layered: root → nested, nearest wins), ignore paths, budget, severity floor, focus, instruction files |
| `context.py` | cheap repo index (tree, imports, symbols, conventions) |
| `lenses.py` | the experts: correctness, security, performance, ui, tests, maintainability + PR-level `merge` |
| `llm.py` | OpenAI-compatible client, key rotation, JSON repair, usage |
| `prompts.py` | review/verify/summary prompts; untrusted-data fencing |
| `verify.py` | machine gate (line exists in diff, evidence quoted) + bounded model gate |
| `secretscan.py` | deterministic regex secret scanner; ground-truth findings, masked, bypass model gate |
| `tickets.py` | linked-issue parse (keyword set) + acceptance-criteria extraction + ticket prompt block |
| `indexer.py` | persistent code graph: stdlib-`ast`/regex parse, incremental `repo_index`, import graph, tests, PageRank retrieval, bounded context pack |
| `recall.py` | prior-review/prior-PR recall: past findings by path (+ outcomes), dismissals, `file_prs` history, bounded recall block |
| `github.py` | REST **and GraphQL**: PR files (paginated), file content, inline review, upsert comment, check runs, `closingIssuesReferences`, issue fetch, PR/commit history |
| `store.py` | SQLite: run idempotency, findings, **file_cache**, **repo_index**/**file_prs** (code graph + file history), delivery dedupe, outcomes → suppression |
| `pipeline.py` | orchestration + `review_pr()` / `review_snippet()` |

Wiring: `routers/webhook.py` → `pipeline.review_pr`; `routers/review.py` → `pipeline.review_snippet`.

## v1 bugs being fixed (audit `../temp/intel/buglens-audit.md`)
- fail-**open** webhook when secret unset → now fail-closed (`core/security.py`)
- raw unified diff sent to the model + invented line numbers → diff-native engine
- 3 disagreeing language maps → single source; `schemas.py` accepts all emitted langs
- `EXTENSION_KEY` vs `EXTENSION_SHARED_SECRET` mismatch → `require_extension_key` fixed
- empty `backend/tests/*.py` → real tests; no CI → GitHub Actions
- `BugAnalytics.html` XSS on `r.ip` → escaped; Postgres-only `pg_insert` → dialect-agnostic

## Working checklist (update status as you go)
- [x] Phase 1 — v2 engine modules
- [x] Phase 2 — wire webhook + review; fix v1 bugs; feedback endpoint; config validation
- [x] Phase 3 — extension.ts (severity adapter, escaping, line mapping, apiUrl); dashboard
- [x] Phase 4 — tests + CI + step-by-step verification (pytest, py_compile, build, boot, signed webhook)
- [x] Phase 5 — ITERATION.md loop (commits still pending explicit user ask)
- [ ] Phase 6 — **critique vs competitors** (Cursor Bugbot, CodeRabbit, Greptile + the 19 OSS
      bots in `../temp/pr-review-bots/`): read their prompts/features/UI/issues and fold in wins.
      Live log in `ITERATION.md`. *(iterations 3–13 shipped consensus, resolution rate,
      reaction feedback, walkthrough, file cache, secret scanner, ticket/spec validation,
      persistent code graph, prior-review recall, layered base-branch rules, IDE
      repo-awareness; iteration 14 = scale/no-waste; iteration 15 = reliability; iteration 16 =
      cost+activation disclosure footer and re-review round cap/convergence. Next (learning
      wave, `temp/intel/buglens-pr-review-learning-2026-10.md`): position-drift gate →
      pre-mortem + depth triggers → risk-tier header/L0–L3 + surprise detector → verifier
      rationale persistence. Pre-merge checks + inline reply chat still open)*

## Folding in competitor features (Phase 6, ongoing)
Already lifted from the space: one-click **suggestion blocks** (Vercel openreview),
on-demand **`@buglens` re-review** (openreview/CodeRabbit), **reaction-style feedback →
suppression** (openreview reactions / Greptile "learns what you don't care about"),
**repo-defined lenses** via markdown (openreview skills / Gitea bot personalities),
**skip-nits + evidence-gated** comments (pr-review-bot / CodeRabbit), AGENTS.md-aware
context (itstimwhite/pr-review-bot).

Latest from Cursor Bugbot (iterations 3–4, implemented): **multiple shuffled review passes +
majority vote** (`consensus:` rule in `.buglens.yml`, default 1/off), **resolution-rate
tracking** on merge (`pipeline.measure_resolution` → `store.resolution_stats`), optional
**check run** (`post_check_run: true`), auto-reading `.cursorrules` /
`.cursor/rules/*.mdc` / `.github/copilot-instructions.md`, and **reaction → feedback** via a
hidden `<!-- buglens:fp=… -->` marker (no client required). Bugbot deliberately skips style
nits and optimizes for "bugs that get fixed" — we match both.

## Store keys (do not regress)
Everything persisted is keyed by **`owner/repo`** (the pipeline normalizes a bare name into
a `slug`). GitHub API calls keep the bare repo name — that is the URL segment, not an
identity. `POST /api/v1/feedback` and `/engine/stats?repo=` expect `owner/repo`.

## Scale rules (iteration 14 — do not regress)
- `store._open()` is the **only** way to touch SQLite: it borrows a pooled connection from a
  bounded per-file pool (`BUGLENS_SQLITE_POOL`). Never call `aiosqlite.connect` directly, and
  never hold a connection across an `await` that can re-enter the store (the pool is bounded,
  so nesting deadlocks). `store.close_pool()` must run on app shutdown — aiosqlite worker
  threads are **non-daemon** and an unclosed pool hangs the interpreter at exit (this is what
  the autouse `_close_store_pool` fixture in `tests/conftest.py` is for).
- WAL is set once in `init()` (it is a file property); `busy_timeout`/`synchronous`/`foreign_keys`
  are per connection. Keep it that way — re-issuing `journal_mode=WAL` per connection was a
  measurable waste.
- Prefer batch store calls (`put_index_many`, `recent_prs_for_paths`) over per-row/per-file
  loops. This is the difference between one round-trip and N.
- `build_graph`/`tests_for`/`related_files` must stay linear-ish: resolve imports via the
  `_module_maps` dictionaries, not by rescanning all modules. `test_build_graph_matches_bruteforce`
  pins the semantics.
- Concurrency limits: `pipeline.MAX_ACTIVE_REVIEWS` (per process, admission control) and
  `pipeline.CONCURRENCY` (per review). All agent/LLM **and GitHub** HTTP goes through the
  shared pools (`llm._http()`, `github._http()`); never construct a client per call. Both are
  closed in the lifespan.
- `pipeline._load_graph()` is the only way to read the code index for retrieval: it caches
  `(index, graph)` keyed by `(db, slug, store.index_version(...))`. The version is a write
  counter bumped by every index write — **never** re-key it on a timestamp or row count
  (second-resolution timestamps and same-count updates both produced stale caches).

## Reliability rules (iteration 15 — do not regress)
- **A review that could not run must never look clean.** Lens calls count `calls`/`errors`
  in their usage dict; `_lens_health()` reads them. All-calls-failed ⇒ status `incomplete`,
  score 0, and a "could not run" comment — never a green summary. Same guard in
  `review_snippet`.
- **Feedback markers are signed.** `pipeline.fingerprint_marker()` emits
  `fp=<hash>.<hmac16>`; `extract_fingerprint()` verifies it whenever
  `GITHUB_WEBHOOK_SECRET` is set. Never re-enable accepting an unsigned marker while a
  secret exists — that is how suppression gets poisoned.
- **Stale runs are reclaimed.** `store.claim_run` re-takes a claimed-but-unfinished run
  after `BUGLENS_STALE_RUN_MIN` minutes; a finished run (`verdict` set) is never reclaimed.
  Use `calendar.timegm`, not `time.mktime`, for the UTC stamps.
- **Best-effort writes never cost the review.** Persisting findings is wrapped; a store
  failure must not abort posting.
- `store.sweep()` runs from `main._sweep_loop()`; do not prune individual index paths —
  a review only knows the files it fetched, so path-level pruning deletes the rest of the index.
- Docs live in `docs/` (engine, api, configuration, operations, faq, contributing). Keep
  `README.md` short — it is a landing page, not a manual.

## Honesty rules (iteration 16 — do not regress)
- **Never fabricate a number.** The `Engine:` footer shows tokens only when the provider
  returned them ("provider reported no token usage" otherwise) and a dollar figure only when
  `BUGLENS_COST_PER_1M_IN`/`_OUT` are configured. No invented prices, no invented `0 tokens`.
- **Name every depth change.** Any optional layer that alters review depth (consensus,
  verify gate + drop stats, secret scan when it flags, ticket check, code graph, recall,
  partial call failures) must appear in `res.engine_notes` — `_engine_notes()` builds them,
  `render_summary_md` prints them. A silent depth change is a bug.
- **Cap the re-review loop.** `rules.max_rounds` (default 10) stops the bot; `rules.converge_rounds`
  (default 3) switches to new-code-only. `round_no` comes from `store.count_rounds` (rows in
  `runs`) — never increment it anywhere else. The convergence filter is `_content_sha` over the
  whole hunk + the `pr_round_files` ledger (`first_round<round_no`); keep it deterministic.
- The round-cap note uses its own marker (`pipeline.MARKER_CAP`); the convergence note reuses
  `MARKER` (it *is* the current review).

## Performance work (how to do it here)
Measure first, with a reproducible harness: `cd backend; python bench.py` (medians of
repeats). Put the numbers in the PR/iteration entry, and cite where they are quoted in
`docs/operations.md`. Numbers measured on a laptop vary ~2x run to run — report ranges and
order-of-magnitude, never a single flattering figure.

## Continuous self-improvement loop (detail in ITERATION.md)
1. Customers/teammates react 👍/👎 on a BugLens comment → `POST /api/v1/feedback` → `store.record_outcome`.
2. 👎 twice on the same fingerprint → it is **suppressed** (`store.suppressed`).
3. 👍 rememberings become **confirmed-good** examples injected into future prompts.
4. Every iteration: re-read competitor intel, list gaps, pick the top one, implement, test, commit.
5. Update this file + `ITERATION.md` after every iteration so the next session has the state.

## Commands
```
# backend (uv venv, NO pip)
C:\Users\purpo\Documents\Anubis\apps\black-hood\buglens\backend\.venv\Scripts\python.exe -m pytest -q      # cwd=backend
# extension
cd vscode-extension; npm run compile
```
Env to test offline: `BUGLENS_DB=:memory:` (or a temp file), `GITHUB_WEBHOOK_SECRET=x`,
`OPENAI_BASE_URL=http://127.0.0.1:4096/v1`, `OPENAI_API_KEY=local`.
