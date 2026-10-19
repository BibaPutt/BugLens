# AGENTS.md: BugLens (read me first, every session)

Working memory for autonomous agents. **If you are an agent picking this up: read this
file, then `ITERATION.md`, then continue the checklist below. Do not ask the user to
re-explain.**

## What this is
BugLens is a code-review product with three surfaces:
1. **PR bot**: a GitHub webhook that reviews pull requests and posts a consolidated review.
2. **VS Code extension** (`vscode-extension/`): reviews the current file in the IDE.
3. **Dashboard** (`BugAnalytics.html`) + FastAPI backend (`backend/`).

Repo: `github.com/Vansh940/BugLens`. Local branch for all v2 work: **`enhance/v2-engine`**.
**Never push to `main`.** Commit locally **as each wave lands**; run `git push` only when the
user says **"final"**. Never print or commit the token.

## Ground rules (locked by the user)
- **Provider-agnostic LLM.** OpenAI-compatible API. Default provider Groq; `OPENAI_BASE_URL`
  can point at a local proxy (e.g. `http://127.0.0.1:4096/v1`) for dev.
- **Never block a PR by default.** Post `event=COMMENT` unless a repo sets
  `request_changes: true` and the verdict is `blocking`; never fail a build. Max-recommended
  guardrail stays off by default.
- **One consolidated review per PR** (inline comments + one summary), never a comment storm.
- **Evidence or it doesn't ship.** Every finding must be anchored to an added line and must
  survive the verify gate (`buglens/verify.py`). No proof → dropped.
- **Idempotent.** Re-running a webhook for the same commit must not double-post.
- **No new required services.** Must run on SQLite + no Redis for local dev/tests.

## Architecture (v2 engine: `backend/buglens/`)
| file | job |
|---|---|
| `diff.py` | parse unified diff, map to **new-file** line numbers, join added text, fingerprints |
| `severity.py` | severity taxonomy (blocker/high/medium/low/info), ranking, comment budget, `priority()` → P1/P2/P3 |
| `dedupe.py` | pure precision pass: `normalize_evidence`/`defect_key`/`dedupe` collapse the same defect raised by several lenses into one finding (kept finding gains `lenses` + `additional` locations) |
| `rules.py` | load `.buglens.yml` (layered: root → nested, nearest wins), ignore paths, budget, severity floor, focus, instruction files |
| `context.py` | cheap repo index (tree, imports, symbols, conventions) |
| `lenses.py` | the experts: correctness, security, performance, ui, tests, maintainability + PR-level `merge` |
| `llm.py` | OpenAI-compatible client, key rotation, JSON repair, usage |
| `prompts.py` | review/verify/summary prompts; untrusted-data fencing |
| `verify.py` | machine gate (line exists in diff, evidence quoted) + bounded model gate |
| `secretscan.py` | deterministic regex secret scanner; ground-truth findings, masked, bypass model gate |
| `adapters.py` | deterministic linters/SAST (ruff, bandit, eslint, node-syntax, shellcheck, hadolint, rubocop, yamllint, php-syntax); ground-truth findings, capped to added lines, bypass model gate, opt-in via `linters:` |
| `tickets.py` | linked-issue parse (keyword set) + acceptance-criteria extraction + ticket prompt block |
| `indexer.py` | persistent code graph: stdlib-`ast`/regex parse, incremental `repo_index`, import graph, tests, PageRank retrieval, bounded context pack |
| `symbols.py` | symbol/contract graph: `changed_defs` (added signature lines), `ripple` (in-repo callers), `ripple_block` (lens context), `ripple_findings` (cross-file inconsistency candidate, gated by verify) |
| `learn.py` | pure, deterministic learning+: `lens_ranking` (demote down-voted lenses), `order_lenses`, `learn_block` (bounded feedback advisory for prompts), `candidate_rules` (human-approved `.buglens.yml` snippets, never auto-applied) |
| `checks.py` | pure finding→check-run mapping: `annotation_level`, `finding_to_annotation`, `annotations_from_findings` (cap + ordering), `annotation_chunks` (50/call), `conclusion_for`, `input_text` (three modes) |
| `recall.py` | prior-review/prior-PR recall: past findings by path (+ outcomes), dismissals, `file_prs` history, bounded recall block |
| `prodcontext.py` | pure ticket↔symbol linking: `map_symbols` (whole-word match of changed symbols in ticket text), `ticket_block` (bounded block), `signals_block` (bounded external-signal block) |
| `integrations.py` | optional self-hosted external context: `configured` (env gate), `collect` (Jira/Linear ticket text + Sentry/Datadog/PostHog signals), fail-soft, off by default, own `_http()` pool closed in lifespan |
| `objects.py` | pure code-object units: `build_units` (group a file's added lines by enclosing changed symbol, `<file>` fallback), `symbol_for` (tag a finding with its unit), `unit_summary` (footer string) |
| `walkthrough.py` | deterministic Change-Stack grouping: classify changed files into ordered chapters (schema→models→logic→api→ui→config→tests→docs), per-chapter notes; no model |
| `premortem.py` | pure risk triggers + depth tier: `triggers` (whole-token path match + added-line volume), `tier` (`quick`/`deep`), `select` (keeps only scenarios anchored on an added line), `render_md`; no model |
| `risktier.py` | pure advisory L0-L3 triage tier: `tier` (findings + risky paths + migration + large diff + weak evidence), `advisory`, `render_header_md`; no model, no extra pass |
| `chat.py` | threaded `@buglens` commands: `parse_command` routing, `answer` (deterministic Change-Stack for `explain`, one bounded `complete_text` for `why`/`ask`), `handoff_prompts` Fix-All, `handle_command` posts an in-thread reply |
| `github.py` | REST **and GraphQL**: PR files (paginated), file content, inline review, upsert comment, check runs (create/update/find with annotations), `closingIssuesReferences`, issue fetch, PR/commit history; **review-comment management**: `list_review_comments`, `reply_review_comment`, `update_review_comment`, `delete_review_comment`, `minimize_comment` (GraphQL, never raises) |
| `store.py` | SQLite: run idempotency, findings, **file_cache**, **repo_index**/**file_prs** (code graph + file history), delivery dedupe, outcomes → suppression, **drops** (verifier rationale) and learned lens/dismissal stats, **posted_comments** (comment lifecycle ledger: fingerprint → path/line/comment_id/node_id/head_sha) |
| `pipeline.py` | orchestration + `review_pr()` / `review_snippet()` |
| `mcp_server.py` | local MCP server over stdio (JSON-RPC 2.0, stdlib only): `list_tools`/`call_tool`/`handle`/`serve`/`main`; six read-only tools, `review` dry-run by default |

Wiring: `routers/webhook.py` → `pipeline.review_pr`; `routers/review.py` → `pipeline.review_snippet`.

## v1 bugs being fixed (audit `../temp/intel/buglens-audit.md`)
- fail-**open** webhook when secret unset → now fail-closed (`core/security.py`)
- raw unified diff sent to the model + invented line numbers → diff-native engine
- 3 disagreeing language maps → single source; `schemas.py` accepts all emitted langs
- `EXTENSION_KEY` vs `EXTENSION_SHARED_SECRET` mismatch → `require_extension_key` fixed
- empty `backend/tests/*.py` → real tests; no CI → GitHub Actions
- `BugAnalytics.html` XSS on `r.ip` → escaped; Postgres-only `pg_insert` → dialect-agnostic

## Working checklist (update status as you go)
- [x] Phase 1: v2 engine modules
- [x] Phase 2: wire webhook + review; fix v1 bugs; feedback endpoint; config validation
- [x] Phase 3: extension.ts (severity adapter, escaping, line mapping, apiUrl); dashboard
- [x] Phase 4: tests + CI + step-by-step verification (pytest, py_compile, build, boot, signed webhook)
- [x] Phase 5: ITERATION.md loop (commits still pending explicit user ask)
- [ ] Phase 6: **critique vs competitors** (Cursor Bugbot, CodeRabbit, Greptile + the 19 OSS
      bots in `../temp/pr-review-bots/`): read their prompts/features/UI/issues and fold in wins.
      Live log in `ITERATION.md`. *(iterations 3–17 shipped consensus, resolution rate,
      reaction feedback, walkthrough, file cache, secret scanner, ticket/spec validation,
      persistent code graph, prior-review recall, layered base-branch rules, IDE
      repo-awareness; iteration 14 = scale/no-waste; iteration 15 = reliability; iteration 16 =
      cost+activation disclosure footer and re-review round cap/convergence; iteration 17 (Wave A)
      = deterministic adapters + anchor re-anchor gate + check-run lite; iteration 18 (Wave B) =
      Change-Stack walkthrough + pre-merge checks + opt-in `request_changes`; iteration 19 (Wave C) =
      threaded `@buglens` Q&A + `/explain /why /fix` commands + Fix-All handoff; iteration 20 (Wave D) =
      symbol/contract graph + ripple analysis of changed signatures; iteration 21 (Wave E) =
      learning+: feedback advisories in the prompt, lens demotion by feedback, human-approved
      `.buglens.yml` candidates (`/engine/learn`), verifier drop rationales persisted; iteration 22 (Wave F) =
      check-run parity: opt-in annotated check runs (severity→level map, 50-per-call chunking,
      `check_run_input` modes, `check_run_grouping`, never blocking by default; needs a GitHub App);
      iteration 23 (Wave G) = code-object lensing: findings grouped by their enclosing changed
      symbol (`objects.py`, `<file>` fallback) and opt-in per-lens comment caps (`lens_caps`);
      iteration 24 (Wave H) = external context: ticket text mapped to changed symbols
      (`prodcontext.py`) plus optional self-hosted production signals (`integrations.py`,
      Jira/Linear/Sentry/Datadog/PostHog, off by default, fail-soft); iteration 25 (Wave J) =
      local MCP server (`mcp_server.py`, stdlib-only JSON-RPC over stdio, six read-only tools,
      `review` dry-run by default). Wave I (runtime proof) was skipped on user instruction.
      iteration 26 (Wave K) = review-grade output + precision: verdict-reason/confidence/merge-risk/
      security-risk header scoped to a commit, P1/P2/P3 priority labels, evidence-first finding
      bodies with a lens list and additional locations, pre-merge checks as a status+fix table,
      cross-lens semantic dedup (`dedupe.py`), and inline-comment lifecycle (acknowledge resolved,
      collapse only confirmed-gone findings) over a       `posted_comments` ledger.
      iteration 27 (Wave L) = the three real findings from an external architecture review, after
      verifying the rest were false: a **could-not-run** notice when the PR files cannot be
      fetched (`403`/`429`/`5xx`), one permanent id-routed chat listener in the IDE panel, and
      deterministic adapters executed off the event loop.
      iteration 28 (Wave M) = pre-mortem + depth tiers: a pure `premortem.py` picks a
      deterministic `quick`/`deep` tier from whole-token path risk (new route, migration,
      auth/security path, large diff) and, on `deep`, renders 2-4 production failure scenarios
      each anchored to a real added line (the tier and count are named in the footer).
      iteration 29 (Wave N) = advisory risk tiers: a pure `risktier.py` composes an L0-L3 triage
      line (`Review depth recommended: L3 - read closely`) from findings, risky paths, a migration,
      a large diff and weak evidence, at zero model cost; it is advisory and never blocks.
      **Full plan:
      `../temp/intel/buglens-v2-beat-plan-2026-10.md` (Waves A–J).** Inline reply chat shipped;
      multi-model consensus (second model) still open)*

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
nits and optimizes for "bugs that get fixed". We match both.

## Store keys (do not regress)
Everything persisted is keyed by **`owner/repo`** (the pipeline normalizes a bare name into
a `slug`). GitHub API calls keep the bare repo name, which is the URL segment, not an
identity. `POST /api/v1/feedback` and `/engine/stats?repo=` expect `owner/repo`.

## Scale rules (iteration 14, do not regress)
- `store._open()` is the **only** way to touch SQLite: it borrows a pooled connection from a
  bounded per-file pool (`BUGLENS_SQLITE_POOL`). Never call `aiosqlite.connect` directly, and
  never hold a connection across an `await` that can re-enter the store (the pool is bounded,
  so nesting deadlocks). `store.close_pool()` must run on app shutdown, because aiosqlite worker
  threads are **non-daemon** and an unclosed pool hangs the interpreter at exit (this is what
  the autouse `_close_store_pool` fixture in `tests/conftest.py` is for).
- WAL is set once in `init()` (it is a file property); `busy_timeout`/`synchronous`/`foreign_keys`
  are per connection. Keep it that way: re-issuing `journal_mode=WAL` per connection was a
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
  counter bumped by every index write. **Never** re-key it on a timestamp or row count
  (second-resolution timestamps and same-count updates both produced stale caches).
- **`db` is resolved, not required.** `_review_pr` and `review_snippet` start with
  `db = db or store.db_path()`. Every `if db` gate below decides whether persisted context is
  *used* (round counting, recall, suppression, cross-push dedupe, ripple fetch, drop rationales,
  the round-file ledger). Callers may omit it, but never leave the resolved value None: the
  webhook path passes nothing, so a raw `if db` silently disabled all of those in production
  while the tests, which always pass a path, stayed green. The same trap applies to any new
  helper: do not gate store work on the caller's argument.

## Reliability rules (iteration 15, do not regress)
- **A review that could not run must never look clean.** Lens calls count `calls`/`errors`
  in their usage dict; `_lens_health()` reads them. All-calls-failed ⇒ status `incomplete`,
  score 0, and a "could not run" comment, never a green summary. Same guard in
  `review_snippet`.
- **Feedback markers are signed.** `pipeline.fingerprint_marker()` emits
  `fp=<hash>.<hmac16>`; `extract_fingerprint()` verifies it whenever
  `GITHUB_WEBHOOK_SECRET` is set. Never re-enable accepting an unsigned marker while a
  secret exists. That is how suppression gets poisoned.
- **Stale runs are reclaimed.** `store.claim_run` re-takes a claimed-but-unfinished run
  after `BUGLENS_STALE_RUN_MIN` minutes; a finished run (`verdict` set) is never reclaimed.
  Use `calendar.timegm`, not `time.mktime`, for the UTC stamps.
- **Best-effort writes never cost the review.** Persisting findings is wrapped; a store
  failure must not abort posting.
- `store.sweep()` runs from `main._sweep_loop()`; do not prune individual index paths:
  a review only knows the files it fetched, so path-level pruning deletes the rest of the index.
- Docs live in `docs/` (engine, api, configuration, operations, faq, contributing). Keep
  `README.md` short: it is a landing page, not a manual.

## Honesty rules (iteration 16, do not regress)
- **Never fabricate a number.** The `Engine:` footer shows tokens only when the provider
  returned them ("provider reported no token usage" otherwise) and a dollar figure only when
  `BUGLENS_COST_PER_1M_IN`/`_OUT` are configured. No invented prices, no invented `0 tokens`.
- **Name every depth change.** Any optional layer that alters review depth (consensus,
  verify gate + drop stats, secret scan when it flags, ticket check, code graph, recall,
  partial call failures) must appear in `res.engine_notes`. `_engine_notes()` builds them,
  `render_summary_md` prints them. A silent depth change is a bug.
- **Cap the re-review loop.** `rules.max_rounds` (default 10) stops the bot; `rules.converge_rounds`
  (default 3) switches to new-code-only. `round_no` comes from `store.count_rounds` (rows in
  `runs`), never increment it anywhere else. The convergence filter is `_content_sha` over the
  whole hunk + the `pr_round_files` ledger (`first_round<round_no`); keep it deterministic.
- The round-cap note uses its own marker (`pipeline.MARKER_CAP`); the convergence note reuses
  `MARKER` (it *is* the current review).

## External context (iteration 24, do not regress)
- **`prodcontext.py` is pure.** `map_symbols` uses ASCII word-boundary matching (`(?<![A-Za-z0-9_])`,
  `(?![A-Za-z0-9_])`), never bare `in`; it skips the `<file>` pseudo-symbol; output is ordered by
  first occurrence in the text, capped at `MAX_SYMBOLS`. No model, no I/O.
- **`integrations.py` is optional and off by default.** `rules.external_context` (empty default) lists
  providers; a missing env var makes `configured` False and the provider is skipped. Every call and
  parse is wrapped: a failure contributes nothing and never fails the review. No new required
  service. Its HTTP client is a module-level lazy pool (`_http()`) closed via `integrations.aclose()`
  in `main` lifespan. **Never log a token or an auth header.**
- **Providers and env.** ticket: `jira` (`JIRA_BASE_URL`/`JIRA_EMAIL`/`JIRA_TOKEN`), `linear`
  (`LINEAR_API_KEY`); signals: `sentry` (`SENTRY_TOKEN`/`SENTRY_ORG`/optional `SENTRY_PROJECT`/
  optional `SENTRY_BASE_URL`), `datadog` (`DD_API_KEY`/`DD_APP_KEY`/optional `DD_SITE`), `posthog`
  (`POSTHOG_API_KEY`/`POSTHOG_PROJECT_ID`/optional `POSTHOG_BASE_URL`). `collect` returns
  `{"tickets": [str], "signals": [dict], "used": [str]}`; `used` names only providers that contributed.
- **Both blocks are bounded and opt-in.** The pipeline appends the ticket-symbol block and the
  signals block to the prompt context only when they are non-empty, and names the contributing
  providers in the footer: `external context: <providers>` (iteration-16 rule).

## MCP server (iteration 25, do not regress)
- **`mcp_server.py` is stdlib-only.** JSON-RPC 2.0 over stdio, hand-rolled. Never add the `mcp`
  package, a third-party dependency, or a network listener; it must stay `python -m
  buglens.mcp_server` with nothing but the engine store behind it.
- **`review` is dry-run by default.** The MCP `review` tool runs `pipeline.review_snippet`; it must
  never post unless a caller explicitly opts out of dry-run. No tool writes to GitHub.
- **One event loop per session.** `serve` runs the whole stdio session on a single asyncio loop
  because the aiosqlite pool must not cross loops (iteration-14 rule). Never `asyncio.run` per
  message.
- **Protocol errors are answered, not guessed.** Unknown method → `-32601`, bad `params` →
  `-32602`, unparseable line → `-32700`, internal failure → `-32603`; a notification (no `id`)
  returns nothing. Never silently drop a request.
- Docs for client wiring live in `docs/operations.md` (`## MCP server`); keep them in step.

## Review-grade output + comment lifecycle (iteration 26, do not regress)
- **`dedupe.py` is pure.** `normalize_evidence` collapses whitespace only; `defect_key` is
  evidence-hash first, then `path|line|category`, then `path|title`; `dedupe` returns
  `(kept, dropped)` and **never mutates** its input. The kept finding gains `lenses` (sorted
  distinct) and `additional` (other `{path,line}`). Never merge findings that share only a title:
  that is how two different bugs become one invisible comment. Dedup runs **after** the verify
  gate and **after** merge-lens re-anchoring, so a merge finding is deduped against its real line.
- **A merge finding is re-anchored, never guessed.** `_pr_shadow` returns `(shadow, line_map)`;
  `_reanchor_merge_findings` maps a `<pull-request>` anchor back to the `(path, line)` it came
  from. A PR-level finding with no mapped line stays PR-level.
- **The header is evidence, not decoration.** `_summarise` returns a dict carrying
  `verdict_reason`, `confidence` (clamped 0–100), `merge_risk`, `security_risk`; the prompt says
  the reason must cite the findings and the risks must follow them. Missing keys degrade to empty,
  never to an invented number. The header also names `checked up to <sha7>`.
- **Priority labels are derived, not stored.** `severity.priority` maps the normalized severity;
  the finding body shows `P1 · Blocker · <category>`. Never persist a P-label.
- **Pre-merge checks are rows, not strings.** `_pre_merge_checks` returns
  `{"check","status","detail","fix"}` and the walkthrough renders them as a table. Still
  informational, still gated by `rules.pre_merge_checks`, still never blocking.
- **A comment is only ever touched when its evidence is verifiably gone.**
  `_reconcile_prior_comments` reads the `posted_comments` ledger, fetches the new file, and:
  replies `fixed in <sha7>` and forgets the row when `rules.acknowledge_resolved` (default true);
  collapses via `minimize_comment(OUTDATED)` and forgets the row when `rules.stale_comments`
  (default true). **A finding that is merely absent from this round is still open and is left
  alone**, and a failed fetch is unknown, never resolved. Never retract or collapse on a guess.
  It runs **before** `_post` so its notes render, and `_post` records what it posted.
- **Name it in the footer.** `merged N duplicate finding(s)`, `addressed findings acknowledged: N`,
  `stale comments retired: N` (iteration-16 "name every depth change" rule). When the summary call
  returns none of `verdict_reason`/`confidence`/`merge_risk`/`security_risk`, append
  `verdict meta: not provided by the model`. Never invent a value to fill the header.
- **The IDE path is not the PR path.** `review_snippet` must not inject prior-review recall into
  the prompt: the user asked about this file, now, and recall there demoted four real defects to a
  prose aside and scored the file clean. The PR bot keeps recall (it must not repeat itself across
  rounds); the IDE gets code-graph context only.

## Risk tiers (iteration 29, do not regress)
- **`risktier.py` is pure and free.** Findings + files in, `{level, reasons, advisory}` out. No
  model, no I/O, no extra pass. It reuses `premortem.tokens` for whole-token path matching; do not
  inline a second path matcher.
- **Advisory, never blocking, never a depth switch.** The line names how closely a *human* should
  read; the depth tier (`premortem`) decides which passes run. Never let the risk tier gate lenses,
  the verify gate or the verdict.
- **Severity is normalized first.** `blocker` -> L3, `major` -> L2 via `sev.normalize`; raw strings
  like `high`/`medium` never match directly (`high` normalizes to `major`).
- **L0 renders nothing.** `render_header_md("L0", ...)` returns `""`; the tier is still computed
  for the API/dashboard.
- **Reasons are named.** At most the first three are printed with the line; the full list stays on
  `res.risk_reasons`. `risk_tiers: false` blanks the tier to `""` and drops the line.

## Pre-mortem and depth tiers (iteration 28, do not regress)
- **`premortem.py` is pure.** Files in, tier/items/markdown out. No model, no I/O. The model call
  lives in `pipeline._premortem` (deep tier only); the module only decides and validates.
- **Triggers match whole path tokens.** `_tokens` splits each segment on non-alphanumerics and the
  needle must equal a token: `auth` must never fire on `author.py`. New-route triggers require
  status `added`/`renamed`; the others apply to any status; `large change` needs 200+ added lines
  across the PR. Adding a needle means adding a *token*, not a substring.
- **`select` is the honesty gate.** An item survives only when its `path` is in the reviewed set
  and its `line` is in `fd.added_line_numbers`; items are deduped by `(path, line)` and capped at
  `MAX_ITEMS` (4). Never relocate an unanchored scenario, never pad. `render_md([])` returns `[]`.
- **The tier is always named.** `_engine_notes` prints `review depth: <tier>` (plus
  `(triggers: ...)` when non-empty) and `pre-mortem: N scenario(s)`; the depth note is emitted
  only while `depth_triggers` is on (the iteration-16 "name every depth change" rule). Setting
  `depth_triggers: false` pins `quick` and emits no depth note.
- **It never blocks and never runs in the IDE.** Like every other layer it is advisory; the snippet
  path does not run a pre-mortem.

## Failure notice and IDE chat (iteration 27, do not regress)
- **A review that could not run says so.** When `github.get_pr_files` raises (403/429/5xx),
  `_review_pr` posts `render_error_md(reason)` under `pipeline.MARKER_ERROR` and still returns
  `status="error"`. This is the reliability rule (iteration 15) applied to the fetch phase: no
  green summary, and no silent blank either. The post is **best-effort** (a hard rate limit
  refuses it too), so the failure is `log.warning`'d regardless, and the run is finished as
  `error` with `res.posted` reflecting what actually happened. Never make this comment mandatory
  or let a post failure raise.
- **`render_error_md` sanitizes its input.** The reason comes from an exception message, which may
  embed model or API output: it is whitespace-flattened, stripped of backticks, and truncated
  before it goes inside a code span. Keep it that way.
- **Adapters run off the event loop.** `adapters.scan` shells out synchronously with a hard
  timeout; both call sites (`_review_pr`, `review_snippet`) use `asyncio.to_thread`. On the loop it
  would stall every other request for up to the timeout per file. Never call it directly again.
- **The IDE chat has exactly one message listener.** It routes by the `id` the webview puts in the
  chat payload and the host echoes back on `chatReply`/`chatError`. Per-send listeners made every
  handler answer every reply (the second question showed the first answer, then unbound, dropping
  the real reply). The extra `id` field is ignored by the backend `ChatRequest`, which is fine.

## Code objects and per-lens caps (iteration 23, do not regress)
- **`objects.py` is pure and deterministic.** `build_units` reuses `symbols.changed_defs` (it does
  not re-parse) and assigns each added line to the last definition at or before it; lines above any
  definition belong to `<file>`. Ordered by `start_line`, capped at `MAX_UNITS`.
- **Findings are tagged, not rewritten.** `symbol_for` sets `f["symbol"]` on kept findings so the
  API/IDE can group them by symbol. Never use the symbol to change the comment body or the anchor.
- **`lens_caps` is opt-in and empty by default.** It caps how many comments one lens contributes to
  the single comment; the global `max_comments` (12) still applies first, and the
  severity-then-confidence order is preserved, so a capped lens keeps its top findings only.
  Values clamp to `>= 0`; malformed entries drop. A cap of `0` silences a lens without disabling it.
- **Name it in the footer.** `code objects: N unit(s) across M file(s)` (via `unit_summary`) and one
  `lens caps: <lens> N` line per lens actually capped (iteration-16 "name every depth change" rule).

## Check runs and annotations (iteration 22, do not regress)
- **`checks.py` is pure.** Findings in, annotation dicts/strings out. No I/O, no model. The
  severity→level map is fixed: `blocker`→`failure`, `major`→`warning`, `minor`/`nit`→`notice`.
  A finding with no `line` (PR-level) has no annotation; `annotations_from_findings` returns
  `(kept, dropped)` where `dropped = len(findings) - len(kept)`.
- **Check runs need a GitHub App.** A PAT gets `403`; `find_check_run` must return `None` on any
  non-2xx and never raise. The whole publish path is wrapped and best-effort: it must never fail
  the review and must stay off unless `post_check_run: true`.
- **Chunk at 50.** GitHub accepts at most 50 annotations per create/update and each update
  *appends* (there is no delete/rewrite). Use `annotation_chunks` and `github.update_check_run`;
  never send one giant list.
- **Never block by default.** The conclusion comes only from `checks.conclusion_for(verdict, base,
  required)`; it returns `failure` ONLY when `required_status_check: true` and the verdict is
  `blocking`. All other paths fall back to `check_run_conclusion` (default `neutral`), and a stray
  `failure` clamps to `neutral` when `required_status_check` is false.
- **Three input modes, one skeleton.** `check_run_input` (`pr_metadata` default | `incremental` |
  `full_diff`) controls only the `output` text, never the annotations. `check_run_grouping`
  (`single` default | `per_lens`) only changes how many check runs are created.
- **Name it in the footer.** When annotations publish, append `check run: N annotation(s)` to
  `res.engine_notes` (iteration-16 "name every depth change" rule).

## Learning+ (iteration 21, do not regress)
- **`learn.py` is pure.** Dicts in, strings/dicts out. No store, model, network, or I/O. Keep it
  that way so the same feedback always renders the same advisory and the same suggestions.
- **Suggestions are never auto-applied.** `candidate_rules` returns `.buglens.yml` snippets a human
  copies in. The real ignore key is **`ignore_paths`** (not `ignore`; `_to_rules` matches attribute
  names, so a wrong key is silently dropped). Demotion suggestions annotate `focus:` as a comment.
- **Demotion never removes a lens.** `lens_ranking` needs `raised >= MIN_SAMPLES (5)` and a
  down-rate `>= DOWN_RATE (0.5)`; `order_lenses` only moves demoted lenses to the end of a file's
  lens list. Named in the footer: `adaptive: N lens(es) demoted by feedback`. The advisory scope
  count is named too: `learned from feedback: N dismissal scope(s)`.
- **Feedback is read, not invented.** `store.lens_outcome_stats` joins `findings`→`runs`→`outcomes`
  on `(fingerprint, repo)`; `dismissal_scopes` needs `downs >= 2` and `downs - ups >= threshold`.
  A lens with no feedback still appears with zeros; a NULL lens groups under `unknown`.
- **Verifier rationale is persisted.** `pipeline` calls `store.save_drops(run_id, slug,
  verified.dropped, db)` best-effort (wrapped, never costs the review); the reason bucket is
  `drop_reason.split(":", 1)[0]` (`machine` / `model` / `suppressed by prior feedback` /
  `unknown`). Read back via `store.drop_stats` and `GET /api/v1/engine/stats` (`drops`).
- **`GET /api/v1/engine/learn?repo=` requires the admin key.** It is read-only: `{repo, lens_stats,
  scopes, candidates}`. Never make it mutate config.

## Symbol graph + ripple (iteration 20, do not regress)
- **`symbols.py` is pure and deterministic.** `changed_defs` reads only added lines;
  `ripple`/`ripple_block`/`ripple_findings` read only the loaded index. No model, no I/O, keep
  it that way so the same inputs give the same output.
- **Ripple callers come from indexed file bodies, not from the diff.** The pipeline fetches up to
  `pipeline.RIPPLE_FETCH` (6) related file bodies, indexes them, then reloads the graph
  (`_load_graph` re-keys on `index_version`, so the reload is correct). If GitHub is not
  configured the fetch is skipped and ripple simply sees the changed files. Never make the fetch
  required and never raise on it, the whole block is wrapped and falls back to an empty ripple.
- **Only one ripple finding exists, and the gate still decides.** A changed definition that now
  takes a **required** (no-default) argument while callers exist. It ships
  `deterministic=False`, `confidence=0.5`, lens `merge`, and a fingerprint; it is dropped unless
  it passes the normal verify gate. Never mark a ripple finding deterministic (that would skip
  the gate).
- **Name it in the footer.** `_engine_notes(..., ripple=len(ripple_items))` prints
  `ripple: N changed symbol(s) with callers`. A depth change that is not named is a bug
  (iteration-16 rule).

## Chat and commands (iteration 19, do not regress)
- **A known verb wins, else "review".** `chat.parse_command`: `@buglens review|re-review`,
  `explain`, `why`, `fix` are explicit; a bare mention or any mention containing the word
  "review" re-runs the review (historical behaviour); everything else is a free-form question.
  Keep that precedence, `@buglens why did the review flag this` must stay a question.
- **Chat re-uses review context, never a second pipeline.** `chat._gather` parses the PR diff,
  loads effective rules and the posted findings (`store.findings_for_pr`); it does not call the
  review engine. `REVIEWABLE_EXTS` is imported lazily from `pipeline` (avoid an import cycle).
- **Only prose costs a model call, and it is bounded.** `explain` and `handoff_prompts` are
  deterministic. `why`/`ask` make one `llm.complete_text` call; on failure `answer` returns the
  honest "model is unreachable" note plus the deterministic Change-Stack, never a fabricated
  answer.
- **Replies are marked and posted as issue comments.** `handle_command` prefixes
  `<!-- buglens:reply:<pr> -->` and posts via `github.post_issue_comment`; a post failure is
  logged, never raised. `review` is handed back to the pipeline, not answered here.

## Walkthrough / Change-Stack (iteration 18, do not regress)
- **`walkthrough.py` is pure and deterministic.** `classify(path)` is first-match-wins with a
  fixed precedence (tests, docs, migration, model, api, ui, config → else logic); `build_change_stack`
  only groups files and attaches findings. No model, no network, no I/O. Keep it that way, the
  walkthrough must render identically from the same inputs.
- **The stack replaces the flat module list.** Render order is the chapter display order
  (`_ORDER`), not insertion order; a chapter with no files is dropped.
- **Pre-merge checks assert observed facts only.** `_pre_merge_checks` lists tests/issue/secrets/
  linters/round from real signals; never add a check that guesses. Gate on `rules.pre_merge_checks`
  (default true); it is informational and never blocks.
- **`request_changes` is the only blocking path, and it is opt-in.** `_post` chooses
  `REQUEST_CHANGES` only when `rules.request_changes` is true *and* `res.verdict == "blocking"`;
  `github.post_review` clamps any other event to `COMMENT`. The default must stay `COMMENT`.

## Deterministic adapters + anchor gate (iteration 17, do not regress)
- **Adapters are opt-in and must never be required.** `linters` defaults to `[]` (off);
  `["auto"]` detects installed tools; you can also name them. A missing tool is a **no-op,
  never an error** and never fails a review. Subprocess only, **no shell**, bounded by
  `BUGLENS_LINTER_TIMEOUT` (default 25s). Never add a required service or a Docker dependency.
- **Ground-truth findings still obey the added-line rule.** Adapter hits set
  `deterministic=True` / `confidence=1.0` and bypass the **model** gate (like `secretscan.py`),
  but they are dropped unless the line is one the PR added. Never let a tool hit point at an
  unchanged line.
- **Anchors re-anchor, they never guess.** `diff.anchor_to_evidence(fd, quote, prefer, min_chars)`
  snaps a finding to the line containing its quoted evidence and records `line_drift`
  (`verify.machine_gate`); if the quote is absent the finding is still dropped. Never post an
  inline comment on a line we cannot prove.
- **Check runs never block by default.** `check_run_conclusion` defaults to `neutral`; a
  `failure` conclusion is only emitted when `required_status_check: true`.
- Adapters must surface in the footer as `linters: <names>` (iteration-16 "name every depth
  change" rule).

## Performance work (how to do it here)
Measure first, with a reproducible harness: `cd backend; python bench.py` (medians of
repeats). Put the numbers in the PR/iteration entry, and cite where they are quoted in
`docs/operations.md`. Numbers measured on a laptop vary ~2x run to run. Report ranges and
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
