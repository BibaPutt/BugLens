<div align="center">

<img src="vscode-extension/icon.png" width="112" alt="BugLens"/>

# BugLens

**AI code review that survives scrutiny.** Diff-native, evidence-gated, and it remembers
what it already told you.

[Install](https://marketplace.visualstudio.com/items?itemName=VanshDev.buglens) ·
[API docs](https://buglens-api.onrender.com/docs) ·
[Engine](docs/engine.md) · [Self-hosting](docs/configuration.md) · [Report a bug](https://github.com/Vansh940/buglens/issues)

</div>

---

Three surfaces, one review engine:

- **VS Code extension** — `Ctrl+Shift+R` reviews the current file or selection, with inline
  highlights and hover fixes.
- **GitHub PR bot** — reviews every pull request, posts one consolidated review with
  apply-in-one-click suggestion blocks. It never blocks a PR.
- **Dashboard + API** — `/api/v1/review`, history, and engine stats.

## Install

```bash
code --install-extension VanshDev.buglens
```

Or: `Ctrl+Shift+X` → search **BugLens** → Install. Then open a file and press `Ctrl+Shift+R`.

## Use

| Action | Shortcut |
|---|---|
| Review file or selection | `Ctrl+Shift+R` / `Cmd+Shift+R` |
| Toolbar | magnifier icon in the editor title bar |
| Right-click | **BugLens: Review This Code** |
| Re-review a PR on demand | comment `@buglens review` |

Point the extension at your own backend with the `buglens.apiUrl` setting.

## Why the output is trustworthy

- **Diff-native.** Every finding is anchored to an added line and quoted with evidence. No
  line, no finding.
- **Two-gate verification.** A machine gate (line exists in the diff, evidence actually
  present) plus a bounded model gate. Deterministic hits — secrets — bypass both.
- **One review per PR.** Never a comment storm; pushes don't duplicate comments.
- **Learns.** 👍/👎 reactions suppress repeated noise and promote patterns into future
  prompts. On merge it checks whether each finding was actually fixed.
- **Codebase-aware.** A persistent local index of the repo brings dependencies, importers,
  tests and earlier reviews into context.

Full detail: **[docs/engine.md](docs/engine.md)**.

## GitHub PR bot

Repo → **Settings → Webhooks → Add webhook**:

| Field | Value |
|---|---|
| Payload URL | `https://your-host/api/v1/webhook` |
| Content type | `application/json` |
| Secret | the same string as `GITHUB_WEBHOOK_SECRET` |
| Events | **Pull requests** only |

Host it yourself with SQLite — no Redis, no queue, no vector DB required. See
[docs/configuration.md](docs/configuration.md).

## Docs

| | |
|---|---|
| [engine.md](docs/engine.md) | lenses, verify gate, tickets, code graph, recall, repo rules |
| [api.md](docs/api.md) | endpoints and request/response examples |
| [configuration.md](docs/configuration.md) | settings, `.buglens.yml`, env vars, deployment |
| [operations.md](docs/operations.md) | concurrency, caching, measured limits, troubleshooting |
| [faq.md](docs/faq.md) | common questions |
| [contributing.md](docs/contributing.md) | dev setup, tests, architecture pointers |

PRs to this repo are reviewed by BugLens itself.

---

MIT licensed. Built by [Vansh](https://github.com/Vansh940).
