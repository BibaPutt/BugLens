# The review engine

The PR bot and the IDE both call one engine (`backend/buglens/`). This page explains what
it actually does to your diff.

## Pipeline

1. **Fetch** the PR: paginated file list, base/head SHAs, linked issues, and the target
   file contents when snippets are needed.
2. **Parse** the unified diff into per-file added lines with **new-file** line numbers.
   Everything downstream refers to those numbers.
3. **Index** the repo. One JSON record per file (defs, imports, refs, doc), keyed by content
   hash, stored in SQLite. Only changed files are re-parsed.
4. **Build context**: the import graph, reverse dependencies, related tests, and a
   personalized PageRank ranking pick up to N related files into a bounded context pack.
5. **Recall** prior findings and prior PRs for the changed files, plus their outcomes.
6. **Review** through lenses. Each lens sees the diff, the repo rules, the code graph pack
   and the recall block. Findings are normalized, de-duplicated by fingerprint, and capped
   by severity budget. Deterministic **adapters** (local linters/SAST, when enabled) run
   alongside the lenses and contribute ground-truth findings with no model call.
7. **Verify**: a machine gate (the line exists in the diff, the quoted evidence is actually
   present, and a drifted anchor is snapped back to its evidence line with the `line_drift`
   recorded), then a bounded model gate (concurrent, top-N only).
8. **Post** one consolidated review: inline comments with suggestion blocks, plus a summary
   comment carrying the walkthrough.
9. **Measure** on merge: re-read the merged files and record whether each finding was fixed.

## Lenses

| Lens | Looks for |
|---|---|
| `correctness` | logic errors, null/undefined, off-by-one, resource leaks, error handling |
| `security` | injection, authz gaps, unsafe deserialization, SSRF, secrets in code |
| `performance` | N+1 queries, blocking I/O, needless allocation, hot-path work |
| `ui` | accessibility, state bugs, layout/reflow, missing loading and error states |
| `tests` | missing or weak coverage for the change, tests asserting nothing |
| `maintainability` | dead code, duplication, unclear names, but only when it matters |
| `merge` | merge-readiness and, when a ticket is linked, spec compliance |

A lens can be scoped to file extensions and severity, and you can add your own. See
**Custom lenses** below.

## Verification, or why you get fewer comments

BugLens is tuned for precision over volume. A finding is dropped unless:

- the quoted **evidence text exists in the added lines** of that file, and
- the line number refers to a line the PR actually added, and
- it passes the model gate (an independent call that argues the finding is false), and
- it survives suppression: two net 👎 from your team on that fingerprint and it never
  appears again.

Three classes bypass the model gate because they are ground truth:

- **Deterministic secret scanner**: regex hits on added lines. The value is masked in the
  output and never sent to the model.
- **Adapter hits**: local linter/SAST output (see **Deterministic linters** below) carries
  `deterministic=true` and is still capped to added lines.
- **Ticket criteria**: assertions about your own acceptance criteria, not code claims.

If a finding's line has drifted since it was anchored (force-push, rebase, retarget), the
machine gate **re-anchors it to the line that actually holds the quoted evidence** and records
the signed `line_drift`; only if the quote is not in the diff at all is the finding dropped.
A real finding is never lost and never posted on the wrong line.

`consensus: 3` in `.buglens.yml` runs three shuffled passes and posts only what wins the
majority. It costs 3x tokens and is off by default.

## Chat and commands

The review is a broadcast; a mention is a conversation. Comment anywhere on the PR (or reply
in an inline review thread) and BugLens answers there, reusing the same context the review
used: a digest of the added lines, the code graph block and the findings it already posted.

| Comment | What happens |
|---|---|
| `@buglens review` / `@buglens re-review` / `@buglens` | runs a fresh review (on demand) |
| `@buglens explain` | a deterministic Change-Stack narrative of what the PR changes |
| `@buglens why` | why a finding matters, grounded in its evidence |
| `@buglens fix` | a concrete fix plus a copy-ready Fix-All prompt for Claude Code, Cursor or Codex |
| `@buglens <question>` | answers the question |

Routing and the Change-Stack narrative are deterministic; only the prose is one bounded model
call. If the model is unreachable the reply says so and falls back to what BugLens knows
without it, rather than inventing an answer. A known verb wins, so `@buglens why did the
review flag this` is a question, while `hey @buglens please review` re-runs the review.

## Deterministic linters (adapters)

Beyond the model, the engine can run real linters/SAST on the added lines and fold their
output in as findings. These are **ground truth**: `deterministic=true`, confidence `1.0`,
and they skip the model gate, so a real bug a tool finds is never argued away by the model.
They are still capped to lines the PR added, so nothing lands on unchanged code.

All of them are **optional and off by default**:

```yaml
linters: auto            # [] = off (default); "auto" = any that are installed; or name them
```

| Adapter | Languages | Notes |
|---|---|---|
| `ruff` | Python | lint + a broad rule set |
| `bandit` | Python | security (SAST) |
| `eslint` | JavaScript, TypeScript | lint |
| `node-syntax` | JavaScript | parse-only syntax check |
| `shellcheck` | Shell, Bash | shell correctness |
| `hadolint` | Dockerfile | Dockerfile lint |
| `rubocop` | Ruby | lint |
| `yamllint` | YAML | lint |
| `php-syntax` | PHP | parse-only syntax check |

Rules:

- **Missing tool = no-op.** If an adapter's binary is not on `PATH`, it is skipped; it never
  errors and never fails a review.
- **Bounded and shell-free.** Each run is a direct subprocess with no shell and a hard timeout
  (`BUGLENS_LINTER_TIMEOUT`, default 25s).
- **Stable fingerprints.** An adapter hit is fingerprinted on `(file, rule, line)` so it is
  de-duplicated and suppressed like any other finding.
- The set that ran is disclosed in the footer as `linters: ruff, eslint`.

## Ticket and spec validation

If a PR says `Closes #42`, the engine resolves the issue (GitHub GraphQL
`closingIssuesReferences`, with a keyword scan of the PR body and commits as fallback),
extracts the acceptance criteria, and reports each as `addressed` / `partial` /
`not_addressed` / `unclear` with the `file:line` that proves it. Unmet criteria become at
most three findings. The verdict is in the walkthrough. Disable with `check_ticket: false`.

## Code graph

The index is deliberately boring: standard-library `ast` for Python, regex for everything
else. No tree-sitter, no external indexer, no vector database, no required service.

It gives each review:

- direct dependencies of the changed files,
- files that import them (who you just broke),
- their tests,
- related files ranked by personalized PageRank seeded on the change.

## Recall: not repeating itself

For every changed file the engine looks up findings it posted before, and their outcomes:

- `fixed`: you fixed it after the review,
- `dismissed`: your team down-voted it,
- `agreed`: up-voted,
- `open`: still stands.

Open items are restated compactly; dismissed ones are suppressed; fixed ones are counted so
the review does not re-litigate. Prior PRs that touched the same files add one line each.

## Repo rules (`.buglens.yml`)

Rules are read from the PR's **base branch**, so a PR cannot change how it is reviewed.
Nested config files apply to their subtree and the nearest one wins.

```yaml
max_comments: 10
min_severity: low
verify: true
skip_nits: true           # no formatting / import-order noise
consensus: 1              # 2-3 = shuffled passes + majority vote
linters: auto             # [] = off; "auto" = detect installed; or [ruff, eslint]
post_check_run: true      # add a neutral BugLens check run
check_run_conclusion: neutral   # failure only when required_status_check: true
required_status_check: false
pre_merge_checks: true    # deterministic pre-merge checklist in the walkthrough
request_changes: false    # opt-in: REQUEST_CHANGES when the verdict is blocking
check_ticket: true        # validate linked issues against the diff
max_rounds: 10            # stop after this many reviews of one PR (0 = no cap)
converge_rounds: 3        # from round 4 only re-review files whose diff changed
ignore_paths: ["*.lock", "dist/*"]
custom_rules:
  - "Never call an external API without an explicit timeout."
```

Instruction files (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.cursor/rules/*.mdc`,
`.github/copilot-instructions.md`) are also picked up, and their bullets become review
rules for the files they cover.

`request_changes` is the **only** setting that can ever post a blocking review. It defaults
to `false`, and even when on it fires only on a `blocking` verdict (a blocker-severity
finding). With it off, every review is `event=COMMENT` and never gates a merge.

## Custom lenses

Drop a markdown file in `.buglens/lenses/`. It runs only on matching files.

```markdown
# API Resilience
exts: py,ts
category: performance
Flag any HTTP call without a timeout, and retries without backoff. Cite the call line.
```

## Feedback loop

- **In the editor or on GitHub**: react 👍/👎 on a posted finding. Each comment carries a
  hidden `<!-- buglens:fp=… -->` marker, so no client is needed. The marker is
  HMAC-signed with `GITHUB_WEBHOOK_SECRET`, which means a forged marker cannot drive fake
  votes to suppress findings.
- **Programmatically**: `POST /api/v1/feedback` with the fingerprint.
- Two net 👎 suppress that fingerprint. 👍 becomes a confirmed-good example injected into
  future prompts.
- On merge, the resolution rate per repo is recorded and exposed at
  `GET /api/v1/engine/repos`.

## Walkthrough

Every PR summary includes a collapsible walkthrough: commits, review effort (1–5), findings
by severity, the ticket verdict, and **which context was used** (code graph file count, linked
ticket, prior reviews) with the base SHA reviewed.

**Change stack.** Instead of a flat file list, the changed files are grouped into ordered
chapters (Schema & migrations → Data models & types → Core logic → API & routes → UI →
Config & infra → Tests → Docs), each with a one-line note: file count, how many are new, and
any findings with their titles. This is pure path heuristics (`walkthrough.py`), no model
call, so it reads like a reviewable stack for free.

**Pre-merge checks.** A short deterministic checklist inside the walkthrough: whether test
files moved with code changes, whether an issue is linked, whether secrets were flagged, and
which linters ran. It states only what the engine actually observed. Turn it off with
`pre_merge_checks: false`. It is informational and never blocks.

## Cost and disclosure

Every consolidated review ends with a compact `Engine:` line: engine calls, failed calls,
tokens (only if the provider reported them), an optional dollar figure (only if
`BUGLENS_COST_PER_1M_IN`/`_OUT` are set) and wall-clock, plus a plain line naming every
optional layer that changed review depth (consensus passes, verify drop stats, secret scan,
adapter linters, linked-ticket check, code graph, prior-review recall, and any partial call
failures). Nothing that changes how deep we looked happens silently, and no number is invented.

Re-review discipline keeps the loop bounded: past `converge_rounds` a PR is only re-reviewed
where the diff actually changed (deterministic content hash, **no model calls** when nothing
did), and past `max_rounds` BugLens posts a round-cap note and stops.
