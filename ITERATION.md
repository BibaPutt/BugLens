# ITERATION.md: the continuous improvement loop

BugLens gets better by reading the field, copying what works, and letting its own
users tell it what to stop saying. This file is the loop's memory. **Every session:
read this, do one iteration from "Backlog", append to "Iteration log", commit.**

## The loop
1. **Signals in**
   - 👍/👎 on a posted finding → `POST /api/v1/feedback` → `store.record_outcome`.
   - 2 net 👎 on a fingerprint → that finding is **suppressed forever** (`store.suppressed`).
   - 👎 "note" text is stored on the outcome; 👍 titles are injected into future prompts
     as confirmed-good practice (`store.confirmed_good`).
   - Dashboard → `GET /api/v1/engine` (lenses + effective rules) and
     `GET /api/v1/engine/stats` (runs / findings / outcomes).
2. **Signals out**: every PR push preserves `dropped` findings with a `drop_reason`
   (`machine:` / `model:` / `suppressed`). Treat a spike in `model:` drops as a prompt bug.
3. **Field scan**: read the competitor intel (`../temp/intel/`) and the cloned OSS bots
   (`../temp/pr-review-bots/`), plus a fresh web search, and write new gaps below.
4. **One iteration**: pick the top backlog item, implement it in `backend/buglens/`
   (or the extension/dashboard), add a test, run `pytest`, run `npm run compile`.
5. **Record**: append a row to the log, tick the backlog item, commit locally.

## Non-negotiables carried into every iteration
- Never block a PR (`event=COMMENT`), one consolidated review, evidence-gated comments.
- Runs on SQLite + no Redis by default; no new *required* services.
- Provider-agnostic LLM (OpenAI-compatible).

## Backlog (ranked; top = next iteration)
1. ~~**Auto-mapping reactions → feedback without a client.**~~ **Shipped (iteration 4):**
   posted findings carry a hidden `<!-- buglens:fp=… -->` marker; the `reaction` webhook
   records 👍/👎 straight into outcomes. Manual `POST /feedback` still works.
2. ~~**Caching identical file reviews.**~~ **Shipped (iteration 7):** `file_cache` table
   keyed by (added lines + rules + lenses); identical diffs within 7 days reuse the lens
   verdict and skip the LLM. `store.get_file_cache` / `put_file_cache`.
3. ~~**Per-language verify gates.**~~ **Shipped (iteration 8):** deterministic secret
   scanner (`buglens/secretscan.py`): regex hits are ground truth, skip the model gate,
   post as `blocker`, values masked. First of the "scanners layer"; more rules can follow.
4. **Token/policy budget with early stop** on huge PRs (dwakshar ai-pr-review-bot does a
   hard token gate; we do a file gate: add a char budget too). *Shipped: `max_file_chars`
   now actually gates oversized files (it was dead config); they appear under "Files skipped".*
5. **Walkthrough comment** (CodeRabbit-style change-by-change summary) as the PR body
   when `summary_only: true`. *Shipped: `summary_only` now truly posts summary-only
   (no inline comments): the flag existed but was never read.*
6. **Multi-model consensus** for high-severity findings only (cheap second model; drop
   if they disagree): optional, off by default. *Multi-pass consensus (shuffled diffs +
   majority vote, `consensus:` rule) shipped in iteration 3; a second model is still open.*
7. ~~**`REQUEST_CHANGES` opt-in** via `.buglens.yml` for teams that want a hard gate
   (still never the default).~~ **Shipped (iteration 18):** `request_changes: true` posts
   `REQUEST_CHANGES` only on a `blocking` verdict; the default stays `COMMENT` forever.
8. **Inline reply chat**: reply to a thread on a BugLens comment (like the Gitea bot's
   conversational mode) using the file context we already fetched.
9. ~~**Ticket-aware review.**~~ **Shipped (iteration 9):** the issues a PR closes are read
   (GraphQL `closingIssuesReferences`, keyword fallback), acceptance criteria are extracted,
   and a `spec` lens reports addressed/partial/not_addressed/unclear with `file:line` proof.
10. ~~**Persistent code graph**~~ **Shipped (iteration 10):** `indexer.py` parses every file
    we fetch (stdlib `ast` + regex fallback), stores an incremental per-file record, and
    hands each lens a ranked related-file context pack (deps, importers, tests, PageRank).
11. ~~**Prior-review recall**~~ **Shipped (iteration 11):** `recall.py` surfaces past findings
    on the same paths with outcomes (`fixed` / `open` / `dismissed`) plus which PRs touched
    the files, and keeps dismissed fingerprints out of new reviews.
12. ~~**Nested rules + base-branch config**~~ **Shipped (iteration 12):** config is
    discovered upward from the changed files (nearest wins), instruction files become team
    rules, and everything is read from the PR base commit so a PR cannot retune its review.
13. ~~**IDE repo-awareness + dashboard**~~ **Shipped (iteration 13):** the extension sends
    repo/branch/imports/related excerpts, `review_snippet` uses the code graph and prior
    reviews, and `GET /api/v1/engine/repos` feeds the dashboard picker.
14. ~~**Cost + activation disclosure footer**~~ **Shipped (iteration 16):** see below.
15. ~~**Re-review round cap + convergence discipline**~~ **Shipped (iteration 16):** see below.
16. ~~**Comment-location verification gate (position drift).**~~ **Shipped (iteration 17):**
    `diff.anchor_to_evidence` + `verify.machine_gate` re-anchor a drifted finding to its evidence
    line (recording `line_drift`) or drop it, never a wrong-line inline comment. Pure-deterministic,
    no LLM. *Learning-wave #11.*

> **Full multi-wave plan:** `temp/intel/buglens-v2-beat-plan-2026-10.md` (Wave A done here; the
> remaining waves are the ranked backlog items 17-21 plus the beat-designs in that file).
17. **Pre-mortem section + quick/deep depth triggers.** A bounded 2–4 item "what fails in
    production" narrative, each traced to a diff line, gated by `depth_triggers` (new public
    route, migration, >300 lines) so typo-fix PRs stay quick. *Learning-wave #9/#8.*
18. **Risk-tier header (L0–L3) + surprise-diff detector.** Zero-LLM-cost tiering from the
    severity histogram + touched-path risk (indexer) + recall outcomes, with deterministic
    scope-anomaly overrides (a UI change touching auth). *Learning-wave #10/#3.*
19. **Verifier decision-with-rationale persistence.** Persist every verify verdict + why, so
    the gate is tunable by data. Prerequisite for the outcome-metrics cluster. *#4.*
20. **GitHub App** (vs webhook secret) so multi-repo install is one click, and reactions
    arrive natively.
21. **Extension**: merge-readiness score for the whole file, and inline VS Code `CodeAction`
    to apply a suggestion (not just copy).

## Iteration log
| # | date | change | signal/inspiration | verified by |
|---|------|--------|--------------------|-------------|
| 1 | 2026-10-18 | v2 engine: diff-native, multi-lens, verify gate, idempotent store, provider-agnostic LLM; v1 bugs fixed; tests + CI | audit `temp/intel/buglens-audit.md`, `competitors.md`, codra/pr-agent | 54 tests pass, `tsc` build, boot smoke |
| 2 | 2026-10-18 | suggestion blocks, `@buglens` on-demand, reaction feedback store, custom lenses, skip-nits | Vercel openreview, itstimwhite/pr-review-bot, Gitea bot | `pytest` (pipeline + webhook tests), `tsc` |
| 3 | 2026-10-18 | shuffled-pass **consensus voting** (`consensus:` rule), merge-time **resolution rate**, optional check run, `.cursorrules`/`.cursor/rules` auto-read, dogfood `.buglens.yml` | Cursor Bugbot blog ("multiple passes + majority vote", resolution-rate metric, plain-English rules) | 59 tests pass (`test_pipeline`, `test_webhook`, `test_rules`) |
| 4 | 2026-10-18 | **reaction → feedback** via hidden fingerprint marker (no client), `reaction` event support, resolution in `/engine/stats?repo=` | Bugbot's "did it get fixed" loop; Vercel openreview reactions | 62 tests pass (`test_webhook` reaction + suppression, `test_pipeline` marker) |
| 5 | 2026-10-18 | wired **dead config**: `max_file_chars` char-budget gate + real `summary_only` (summary-only posting); moved `GITHUB_TOKEN` check after feedback path so reaction webhooks work tokenless | audit of `rules.py` vs usage; dwakshar token gate | 64 tests pass, boot smoke (stats 200, reaction `feedback-recorded`) |
| 6 | 2026-10-18 | **Walkthrough** digest in the summary (commits, effort 1–5, per-module files, severity counts) + **context sources** line | CodeRabbit/CodePeel walkthroughs, CodeRabbit "source line" transparency | 66 tests pass (`test_pipeline` walkthrough) |
| 7 | 2026-10-18 | **File-review cache** (`file_cache` table, 7-day TTL, key = added lines + rules + lenses): skips the LLM on identical diffs | v1 cache done right; large-PR cost | 68 tests pass (`test_store`, `test_pipeline` cache) |
| 8 | 2026-10-18 | **Deterministic secret scanner** (`secretscan.py`): regex ground-truth findings, masked evidence, bypass model gate, posted as `blocker` | CodeRabbit "40+ scanners" layer, scoped down; MSR'26 signal-to-noise findings | 71 tests pass (`test_secretscan`) |
| 9 | 2026-10-18 | **Ticket/spec validation**: `tickets.py` (keyword parse + acceptance criteria), GitHub **GraphQL `closingIssuesReferences`** with keyword fallback, `spec` lens verdicts addressed/partial/not_addressed/unclear, `Ticket:` line in the walkthrough, `check_ticket:` rule | CodeRabbit linked-issue validation; Greptile Jira/Linear ingestion | 80 tests pass (`test_tickets`, `test_pipeline` spec lens), boot smoke (engine 200) |
| 10 | 2026-10-18 | **Persistent code graph**: `indexer.py` (stdlib `ast` + regex fallback), incremental per-file index (`repo_index`), import graph, reverse deps, `tests_for`, personalized-PageRank file retrieval and a bounded `context_pack` fed to every lens; cache key now salts on context | Greptile/CodeRabbit "codegraph", Aider repo-map PageRank | 90 tests pass (`test_indexer`, `test_pipeline` graph context), boot smoke (engine 200) |
| 11 | 2026-10-18 | **Prior-review / prior-PR recall**: `recall.py` (`prior_findings`, `dismissed`, `remember_history` → `file_prs`), ≤8-bullet context block distinguishing *fixed / open / dismissed*, "prior reviews" in Context used; **repo-slug normalization** (all store keys now `owner/repo`) | Greptile knowledge base, CodeRabbit "remembers past comments" | 97 tests pass (`test_recall`, `test_pipeline` recall), boot smoke |
| 12 | 2026-10-18 | **Layered, base-branch rules**: config discovered **upward** from the changed files (`rules.config_candidates`), each later (nearer) file wins, `AGENTS.md`/`.cursorrules` become team rules, everything read at the PR **base** commit so a PR cannot change how it is reviewed | Cursor Bugbot (community rules upward, config from base branch) | 103 tests pass (`test_rules` layered, `test_pipeline` base-ref + nested) |
| 13 | 2026-10-18 | **IDE repo-awareness + repos endpoint**: extension sends `repo`/`branch`/`imports` + up to 5 related-file excerpts; `review_snippet` indexes them and injects graph + recall context; `store.known_repos()` + `GET /api/v1/engine/repos` | Greptile "same context everywhere"; dashboard/onboarding | 105 tests pass, `tsc` build clean, boot smoke (`/engine/repos` 200) |
| 14 | 2026-10-18 | **Scale + no-waste pass** (measure → fix → re-measure with `backend/bench.py`): SQLite **WAL + busy_timeout + bounded connection pool** (was one connect/thread per store call), batched `put_index_many`/`prune_index`, single-query `known_repos` + `recent_prs_for_paths`; **global review admission control** (`MAX_ACTIVE_REVIEWS`) + per-repo lock; **shared keep-alive HTTP pool** for the LLM (was a client per call); concurrent verify gates (was one round-trip per finding); **quadratic `build_graph` replaced by dictionary lookups** (9.4s → ~30ms on 2000 files, equivalence-tested); docs split into `docs/`, README cut to ~90 lines | Industry-standard patterns: WAL/connection pooling, bounded concurrency, admission control, keep-alive pooling, removing O(n²) | 110 tests pass (`test_indexer` graph equivalence, `test_store` WAL/bounded-pool/concurrent-writers), boot smoke |
| 15 | 2026-10-18 | **Reliability pass on the architecture review** (every claim verified against code first): *hollow review* fixed: a failed lens call returned an error dict that `_merge_usage` silently dropped, so a total provider outage posted `looks-good/100`; now calls/errors are counted and an all-failed review posts "could not run" and records `incomplete`. Also: **abandoned-run recovery** (`BUGLENS_STALE_RUN_MIN`, a crashed claim no longer blocks the revision forever), **signed fingerprint markers** (HMAC: a forged `<!-- buglens:fp=… -->` can no longer poison suppression), **shared GitHub HTTP pool** (was a client per call), **parallel file fetches** (20–30 sequential round-trips → bounded gather), **exact in-process code-graph cache** (22 ms → ~1 ms, versioned by a DB write counter), **bounded per-repo locks** (were retained forever), **paginated comment upsert** (>100 comments duplicated the summary), **`save_findings` no longer fatal**, **daily sweep** for file-cache/repo-index growth | Principal-engineer review of the codebase; standard reliability patterns (fail loud, reclaim stale work, authenticate feedback, keep-alive pooling, bound everything, invalidate caches exactly) | 120 tests pass (`test_pipeline` incomplete-review/cache/locks/concurrent-fetch, `test_store` stale-claim/sweep/version, `test_webhook` forged-marker rejection), boot smoke |
| 16 | 2026-10-18 | **Honesty + convergence pass** (from the 13-post PR-review learning wave, `temp/intel/buglens-pr-review-learning-2026-10.md`): every consolidated review now ends with an **`Engine:` cost line**: calls, failures, tokens (only when the provider reports them) and wall-clock, with a **dollar figure only when `BUGLENS_COST_PER_1M_IN/_OUT` are set** (never invented), plus a plain line disclosing every optional layer that changed depth (consensus N, verify stats, secret scan, ticket check, code graph, recall, partial failures). **Re-review discipline**: `max_rounds` (10) and `converge_rounds` (3) in `.buglens.yml`: past `converge_rounds` only files whose reviewed content changed are re-reviewed (deterministic content hash, `pr_round_files` ledger), and past `max_rounds` a round-cap note is upserted and the bot stops (the agent-writes / agent-reviews loop is the documented #1 cost sink) | Learning wave: usage-trust backlash (#5), revert-rate guardrail (#3), Codex denial circuit-breaker (#4), Cursor sub-4-min budget (#12) | 132 tests pass (`test_pipeline` footer/round-cap/convergence, `test_store` round ledger, `test_rules` knobs), boot smoke |

| 17 | 2026-10-19 | **Wave A of the beat-plan** (`temp/intel/buglens-v2-beat-plan-2026-10.md`): **deterministic adapter layer** (`adapters.py`: ruff, bandit, eslint, node-syntax, shellcheck, hadolint, rubocop, yamllint, php-syntax) whose hits post as ground-truth findings (`deterministic=True`, confidence 1.0) that bypass the model gate and are capped to added lines; **anchor re-anchor gate** (`diff.anchor_to_evidence` + `verify.machine_gate`): a drifted line snaps to its evidence quote and records `line_drift` instead of being dropped or posted on a wrong line; **check-run lite** (`post_check_run` / `check_run_conclusion` / `required_status_check`, fail-safe `neutral`); new `.buglens.yml` keys `linters` / `check_run_*` | Beat-plan Wave A; CodeRabbit "40+ scanners", reviewdog (MIT) adapter pattern, pr-agent | 145 tests pass (`test_adapters`, `test_verify` anchor, `test_rules`, `test_pipeline` lint merge) |
| 18 | 2026-10-19 | **Wave B (W4) of the beat-plan**: **Change-Stack walkthrough** (`walkthrough.py`, deterministic path heuristics, no model) grouping changed files into ordered chapters (schema → models → logic → api → ui → config → tests → docs) with a note per chapter (file count, new count, top findings); **pre-merge checks** block (`_pre_merge_checks`, `pre_merge_checks` rule, default true, informational only); **opt-in `request_changes`** (default false; `_post` posts `REQUEST_CHANGES` only on a `blocking` verdict, `github.post_review` clamps the event) | Beat-plan Wave B; CodeRabbit/Graphite change-by-change walkthrough; backlog item 7 | 152 tests pass (`test_walkthrough` new; `test_pipeline` stack + pre-merge + request-changes opt-in; `test_rules` knobs) |

## Change-Stack walkthrough + pre-merge checks (iteration 18)
CodeRabbit spends a model call narrating the change; Graphite's "stack" is the shape reviewers
actually want. Ours is deterministic (`walkthrough.py`):

- `classify(path)` puts each changed file in one chapter, first-match-wins, with a fixed
  precedence so `tests/test_models.py` is a test and not a model.
- `build_change_stack(files, findings)` returns chapters in dependency display order
  (schema → models → logic → api → ui → config → tests → docs), each with a note: `N file(s)`,
  how many are new, and any findings (count + top titles). No model, no I/O; same input, same
  output.
- `_walkthrough_md` renders the stack and, when `pre_merge_checks` is on, a short checklist
  (`_pre_merge_checks`): tests moved with code, issue linked, secrets flagged, linters that ran,
  re-review round. It states only what the engine observed; it never blocks.
- `request_changes` (default false) is the single blocking path: `_post` posts
  `REQUEST_CHANGES` only when the rule is on **and** the verdict is `blocking`; otherwise
  `COMMENT`. `github.post_review` accepts an `event` and clamps anything unexpected to `COMMENT`.

## Deterministic adapters + anchor gate (iteration 17)
Wave A of the beat-plan: ground-truth tool output, and no more wrong-line comments.

- **Adapters (`adapters.py`).** Local linters/SAST, one per language, all optional and **off by
  default** (`linters:` in `.buglens.yml`): `ruff`, `bandit` (Python), `eslint` (JS/TS),
  `node-syntax`, `shellcheck` (Bash), `hadolint` (Dockerfile), `rubocop` (Ruby), `yamllint`,
  `php-syntax`. `linters: auto` detects which are installed. Hits are findings with
  `deterministic=True`, `confidence=1.0`, `linter=<tool>`; they bypass the **model** gate (like
  the secret scanner) but are still **capped to lines the PR added**. A missing tool is a no-op,
  never an error; each run is a bounded subprocess (no shell) with `BUGLENS_LINTER_TIMEOUT`
  (default 25s).
- **Anchor gate (`diff.anchor_to_evidence`).** When a finding's line number drifts from its
  quoted evidence (force-push, rebase, retarget), `verify.machine_gate` re-anchors it to the line
  that actually contains the quote and records the signed `line_drift`, instead of dropping a real
  finding or posting it on a wrong line. If the quote is not in the diff at all, the finding is
  still dropped (evidence rule unchanged).
- **Check-run lite.** `post_check_run` (default false) posts one check run per review;
  `check_run_conclusion` defaults to `neutral`; a `failure` conclusion is only emitted when
  `required_status_check: true`, so the default can never block a PR.
- Adapters are disclosed in the footer as `linters: ruff, eslint` (the "name every depth change"
  rule from iteration 16).

## Cost honesty + convergence discipline (iteration 16)
Two failure modes the whole 2026 field converged on: **nobody trusts usage they cannot see**,
and **agent-writes-code / agent-reviews-code loops forever**.

The consolidated comment now ends with up to two disclosure lines:

```
<sub>Engine: 46 engine call(s), 8 failed · ~41.2k tokens (38.0k in / 3.2k out) · ~$0.013 · 3m05s</sub>
<sub>consensus 3 passes · verify dropped 6 of 18 candidate(s) · secret scan flagged · linked-ticket check · code graph: 120 file(s) · partial: 8/46 model call(s) failed</sub>
```

Rules the renderer obeys (`pipeline._engine_stats` / `_engine_notes`):
- **Tokens only if reported.** A provider that returns no `usage` yields "provider reported no
  token usage", never a fabricated `0`.
- **Dollars only if priced.** A dollar figure appears only when `BUGLENS_COST_PER_1M_IN` /
  `_OUT` are set; a confidently wrong price is worse than none.
- **Depth changes are named.** Anything that changes how deep we looked (consensus passes,
  verify on/off + its drop count, the always-on secret scan *when it flagged*, the ticket
  check, the code graph, prior-review recall) is stated in one plain line.

Re-review discipline is two knobs in `.buglens.yml`:
```
max_rounds: 10        # 0 disables the cap
converge_rounds: 3    # from round 4 only code new since a prior round
```
- `store.count_rounds(repo, pr)` = rows in `runs` for the PR (a duplicate delivery or a draft
  skip never counts: it never reaches `claim_run`).
- Past `converge_rounds`, `pipeline` hashes each file's whole hunk (`_content_sha`, kind+text)
  and, via the `pr_round_files` ledger, keeps only files not already reviewed → **zero model
  calls** when nothing changed, and a "N rounds without convergence" note in the summary.
- Past `max_rounds`, it upserts a round-cap note under its own `<!-- buglens:round-cap -->`
  marker (so the last review comment is left intact) and stops.

## Layered rules at the base commit (iteration 12)
Cursor Bugbot's model: rules come from the files a PR touches, discovered by walking **up**
the tree, and the config is read from the **base branch** so a PR cannot rewrite its own
review. Ours:

- `rules.config_candidates(changed_paths)` returns root config names first, then every
  ancestor directory of every changed file from shallow to deep, each with
  `.buglens.yml|.yaml|.json` plus `AGENTS.md` / `.cursorrules` / `CLAUDE.md`.
- `load_rules(configs)` applies them **in order**: nearest wins, values from wider scopes
  survive. Bullet lines from instruction files are appended to `custom_rules`.
- `pipeline.load_rules_for_pr(owner, repo, ref, changed_paths, cache)` fetches at `ref`
  (always the base commit) and caches within the run; the pipeline makes two passes (root
  before the file list is known, nested after) at the cost of one fetch per file.
- `rules=rules` passed explicitly still bypasses config loading entirely (tests, callers).

## IDE repo-awareness (iteration 13)
The extension now tells the backend which repo it is in (`getRepoSlug()` parses
`.git/config`), the branch, the module specs the file imports (`collectImports`, per
language) and excerpts of up to 5 local imports (`collectRelated`, via `workspace.fs`).
`review_snippet(..., repo=, related=, imports=)` indexes those files, builds the code graph
and pulls the same related-file pack + prior-review block the PR bot uses, so an IDE
finding lines up with the PR finding. `GET /api/v1/engine/repos` lists the repos the store
knows (runs, posted, resolution rate) for the dashboard picker.

## Recall: never repeat ourselves, never re-raise what was dismissed (iteration 11)
Greptile keeps a knowledge base of past reviews; CodeRabbit explicitly checks its own past
comments before posting. We already had the raw material (`findings`, `outcomes`), so
`recall.py` turns it into context:

- `prior_findings(repo, paths)` joins posted findings on the **changed files** to their
  outcome verdicts; each one is classified `fixed` (resolved), `dismissed` (2+ 👎),
  `agreed` (👍) or `open`.
- `recall_block(repo, paths)` renders a ≤8-bullet digest: open/agreed findings with their
  PR numbers, a count of what was fixed, a count of what was dismissed, and which PR last
  touched each file. Fixes and dismissals are summarized, never re-raised as findings.
- `remember_history(repo, paths)` fills `file_prs` from GitHub (`commits?path=` →
  `commits/{sha}/pulls`), capped at 5 files per review and skipped for files we already
  have history for, so repeated reviews cost zero extra API calls.
- The block is appended to the review context under a hard char budget and shows up as
  `prior reviews` in the walkthrough's "Context used" line.

**Bug found while building it:** the pipeline wrote `runs`/`findings`/`outcomes` under the
bare repo name while the webhook reaction handler and `measure_resolution` used
`owner/repo`, so suppression and resolution could never see the same rows. `review_pr` now
normalizes to a single `slug` (`owner/repo`) for every store key; GitHub API calls keep the
bare name because that is the URL, not an identity. (Feedbacks posted via
`POST /api/v1/feedback` should send `owner/repo` too.)

## Code graph (iteration 10)
Greptile and CodeRabbit both review against a repo-wide graph instead of a single diff.
Ours is deliberately dependency-free (`indexer.py`):

- `parse_text(path, text)` → defs (functions/methods/classes + signatures + docstrings),
  imports, call references, `tests` flag. Python is parsed with stdlib `ast`; other
  languages use a conservative regex fallback (JS/TS/Go/Rust/Java-likes).
- `index_files(repo, files, db)` stores one JSON record per file in `repo_index`, keyed by
  a content hash, so a re-push re-parses nothing; `prune=True` drops files that left the tree.
- `build_graph` resolves in-repo imports to paths; `reverse_deps` finds importers;
  `tests_for` finds test files that import or reference the changed symbols.
- `related_files` orders neighbours: direct deps → importers → referencing files → tests →
  personalized **PageRank** over the import graph (Aider's trick, no embeddings).
- `context_pack` renders a bounded block that is injected as **RELATED FILES** into every
  lens prompt; the walkthrough's "Context used" line now reports `code graph (N files)`.

The file cache key includes a hash of the graph context and ticket, so a cached verdict is
never reused against different context. Everything is best-effort: a graph failure falls
back to the tree/snippet context and never fails a review.

## Ticket / spec validation (iteration 9)
CodeRabbit reads the issue a PR closes and reports whether the change actually does it.
We do the same with GitHub alone:

1. `github.closing_issues()` asks GraphQL for `closingIssuesReferences` (respects the
   default-branch rule). If that is empty we fall back to `tickets.parse_closing_refs()`
   over the PR body + commit messages (GitHub's keyword set: `close|closes|closed`,
   `fix|fixes|fixed`, `resolve|resolves|resolved`, `#N`, `owner/repo#N`, issue URLs),
   ignoring code fences, inline code, blockquotes and HTML comments.
2. `tickets.extract_acceptance_criteria()` pulls `- [ ]` items under an
   acceptance/requirement/todo heading; `format_ticket()` renders a compact block that is
   appended to the review context **and** fed to the PR-level `spec` lens.
3. The `spec` lens (`prompts.SPEC_SYSTEM`, `SPEC_SCHEMA`) returns per-criterion verdicts and
   cites `file:line`. Unmet/partial criteria become at most 3 findings tagged `"ticket": true`
   (severity `major`/`minor`, category `merge`); the model/evidence gate is bypassed for them
   because they are PR-level verdicts with no single line, and they never invent requirements.
4. `rules.check_ticket` (default `true`) turns the whole thing off; any GitHub failure is
   swallowed. Spec context is a bonus, never a reason to fail a review.

## Resolution rate (the metric that keeps us honest)
On `pull_request.closed` with `merged: true`, the webhook calls
`pipeline.measure_resolution(owner, repo, pr, merge_sha)`. For every finding we posted,
it re-fetches the merged file: if the quoted evidence is gone (or the file is gone) the
author fixed it → `resolved`; otherwise `unresolved`. These land in `outcomes` under those
two verdicts and are aggregated by `store.resolution_stats(repo)`:

```python
{"resolved": 12, "unresolved": 3, "rate": 0.8}
```

They are deliberately **not** part of the suppression math (`suppressed()` only counts
`down`): resolution is a quality signal for us, not a preference signal from the team.

## Consensus voting (`consensus:` in `.buglens.yml`)
```
consensus: 3   # default 1 = off
```
Each lens runs N times; passes 2..N see the same lines **shuffled** (line numbers kept),
which breaks positional bias. A finding is kept only if it appears in
`floor(N/2)+1` passes (matched by fingerprint). Costs ~N× tokens, so it is opt-in and
worth it on high-traffic repos. This is Cursor Bugbot's precision trick, scoped down.

## How to add a lens (no engine code needed)
Drop `.buglens/lenses/<name>.md` in the target repo:
```
# SQL Safety
exts: sql
category: security
No string-built queries; flag SELECT *, missing WHERE on UPDATE/DELETE.
```
It is loaded per-PR and runs only on matching files. Same shape as the built-ins.
