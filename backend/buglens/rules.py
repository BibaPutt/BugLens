"""Repo-local review rules: `.buglens.yml` (or .buglens.yaml / .buglens.json).

Modelled on Bugbot Rules, CodeRabbit's repo config and Greptile's plain-English
rules: the repo decides what is in scope, how loud the bot may be, and what its
own conventions are. Parsing is deliberately dependency-free, PyYAML if it is
importable, otherwise a small parser for the subset we document.
"""
from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field

CONFIG_NAMES = (".buglens.yml", ".buglens.yaml", ".buglens.json", ".github/buglens.yml", ".github/buglens.yaml")

DEFAULTS = {
    "max_comments": 12,
    "min_severity": "nit",
    "max_files": 25,
    "max_file_chars": 24000,
    "verify": True,
    "verify_top_n": 15,
    "consensus": 1,
    "skip_drafts": True,
    "skip_bot_prs": True,
    "skip_nits": True,
    "post_check_run": False,
    "check_run_name": "BugLens",
    "check_run_conclusion": "neutral",
    "required_status_check": False,
    "linters": [],
    "require_evidence": True,
    "summary_only": False,
    "check_ticket": True,
    "max_rounds": 10,
    "converge_rounds": 3,
}


@dataclass
class Rules:
    max_comments: int = 12
    min_severity: str = "nit"
    max_files: int = 25
    max_file_chars: int = 24000
    verify: bool = True
    verify_top_n: int = 15
    consensus: int = 1
    skip_drafts: bool = True
    skip_bot_prs: bool = True
    skip_nits: bool = True
    post_check_run: bool = False
    check_run_name: str = "BugLens"
    check_run_conclusion: str = "neutral"   # neutral | success | failure; failure needs required_status_check
    required_status_check: bool = False
    linters: list[str] = field(default_factory=list)   # [] off, ["auto"] all installed, or names
    require_evidence: bool = True
    summary_only: bool = False
    check_ticket: bool = True
    max_rounds: int = 10                 # 0 disables the re-review cap
    converge_rounds: int = 3             # from round N+1 only code new since a prior round
    ignore_paths: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    custom_rules: list[str] = field(default_factory=list)
    language_hints: dict[str, str] = field(default_factory=dict)
    source: str = "defaults"
    raw: dict = field(default_factory=dict)


def _coerce(value):
    if isinstance(value, str):
        v = value.strip().strip('"').strip("'")
        if v.lower() in ("true", "yes", "on"):
            return True
        if v.lower() in ("false", "no", "off"):
            return False
        if v.isdigit():
            return int(v)
        return v
    return value


def parse_yaml_subset(text: str) -> dict:
    """Enough YAML for the documented rule file: scalars, one nesting level, lists.

    Handles: `key: value`, `key:` + indented block, `- item` lists, quoted
    strings, inline `[a, b]` lists. Anything it cannot read raises ValueError and
    the caller falls back to defaults rather than guessing.
    """
    root: dict = {}
    stack: list[tuple[int, dict | list]] = [(-1, root)]
    lines = [(len(l) - len(l.lstrip()), l.strip()) for l in text.splitlines()]
    for indent, line in lines:
        if not line or line.startswith("#"):
            continue
        while stack and indent <= stack[-1][0] and len(stack) > 1:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item = _coerce(line[2:])
            if isinstance(parent, list):
                parent.append(item)
            continue
        if ":" not in line:
            raise ValueError(f"cannot parse line: {line!r}")
        key, _, rest = line.partition(":")
        key, rest = key.strip(), rest.strip()
        if rest == "":
            child: dict | list = {}
            target = child
        elif rest.startswith("[") and rest.endswith("]"):
            target = [_coerce(p) for p in rest[1:-1].split(",") if p.strip()]
            child = target
        else:
            target = _coerce(rest)
            child = target
        if isinstance(parent, dict):
            parent[key] = child
        if isinstance(child, dict):
            stack.append((indent, child))
        elif isinstance(child, list):
            stack.append((indent, child))
        elif isinstance(parent, dict) and key in parent and isinstance(parent[key], dict) is False:
            pass
    # a list block written as "key:" then "- item" lines needs a second pass
    return root


def _parse(text: str, name: str) -> dict:
    if name.endswith(".json"):
        return json.loads(text)
    try:
        import yaml  # type: ignore
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}
    except ImportError:
        pass
    except Exception as exc:                      # malformed yaml -> subset parser
        try:
            return parse_yaml_subset(text)
        except Exception:
            raise ValueError(f"invalid rules file {name}: {exc}") from exc
    return parse_yaml_subset(text)


def _to_rules(data: dict, source: str) -> Rules:
    r = Rules(source=source, raw=data)
    known = {k for k in vars(r) if not k.startswith("_")} - {"source", "raw"}
    for key, value in data.items():
        key = key.strip().replace("-", "_")
        rules_key = {"review": "review"}.get(key, key)
        if key in known:
            if isinstance(getattr(r, key), bool):
                setattr(r, key, bool(value))
            elif isinstance(getattr(r, key), int) and not isinstance(value, bool):
                try:
                    setattr(r, key, int(value))
                except (TypeError, ValueError):
                    pass
            else:
                setattr(r, key, value)
        elif key == "review" and isinstance(value, dict):
            inner = _to_rules(value, source)
            for k in known:
                setattr(r, k, getattr(inner, k))
    # lists may arrive as comma strings from the subset parser
    for listkey in ("ignore_paths", "focus", "custom_rules", "linters"):
        v = getattr(r, listkey)
        if isinstance(v, str):
            setattr(r, listkey, [p.strip() for p in v.split(",") if p.strip()])
        elif isinstance(v, bool):
            # `linters: true` in YAML means "auto", `false` means off.
            setattr(r, listkey, ["auto"] if v and listkey == "linters" else [])
        elif isinstance(v, list):
            setattr(r, listkey, [_coerce(x) for x in v])
    r.linters = [str(x).strip().lower() for x in r.linters if str(x).strip()]
    if not isinstance(r.language_hints, dict):
        r.language_hints = {}
    if r.max_comments < 1:
        r.max_comments = 1
    if r.max_rounds < 0:
        r.max_rounds = 0
    if r.converge_rounds < 0:
        r.converge_rounds = 0
    _ = rules_key
    return r


NESTED_NAMES = (".buglens.yml", ".buglens.yaml", ".buglens.json")

# Agent/rule files that, when found in a directory, become team rules for that subtree.
INSTRUCTION_NAMES = ("AGENTS.md", ".cursorrules", "CLAUDE.md")


def config_candidates(changed_paths: list[str] | None = None, limit: int = 40) -> list[str]:
    """Config paths to fetch, in precedence order: repo root first, then each changed
    file's directory from shallow to deep, so the **nearest** config wins.

    This is Cursor Bugbot's model, community rules are discovered by walking *up* from the
    files a PR touches, not from a fixed root file.
    """
    out: list[str] = list(CONFIG_NAMES)
    dirs: list[str] = []
    for path in (changed_paths or [])[:25]:
        parts = path.replace("\\", "/").split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            if d and d not in dirs:
                dirs.append(d)
    dirs.sort(key=lambda d: d.count("/"))
    for d in dirs:
        for name in NESTED_NAMES:
            out.append(f"{d}/{name}")
        for name in INSTRUCTION_NAMES:
            out.append(f"{d}/{name}")
    return out[:limit]


def load_rules(configs: dict[str, str] | None = None, defaults: dict | None = None) -> Rules:
    """Build rules from {path: file_text}, applying them **in order** (nearest wins).

    ``configs`` should be ordered root-first (see ``config_candidates``); each later file
    overrides the keys it sets. Instruction files (AGENTS.md / .cursorrules) contribute
    team rules text for their subtree.
    """
    base = dict(DEFAULTS)
    if defaults:
        base.update(defaults)
    configs = configs or {}
    merged = dict(base)
    winner = "defaults"
    root_name = next((n for n in CONFIG_NAMES if n in configs), None)
    if root_name:
        merged.update(_parse(configs[root_name], root_name))
        winner = root_name
    extra_rules: list[str] = []
    for name, text in configs.items():
        if name in CONFIG_NAMES:
            continue
        clean = name.replace("\\", "/")
        if any(clean.endswith(n) for n in INSTRUCTION_NAMES):
            body = _instruction_rules(text)
            if body:
                extra_rules.extend(body)
            continue
        merged.update(_parse(text, clean))
        winner = clean
    if extra_rules:
        merged["custom_rules"] = list(merged.get("custom_rules") or []) + extra_rules
    return _to_rules(merged, winner)


def _instruction_rules(text: str, limit: int = 12) -> list[str]:
    """Turn an AGENTS.md/.cursorrules body into a few terse, prompt-safe rules."""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")) and len(s) > 3:
            out.append(s[2:].strip())
        if len(out) >= limit:
            break
    return out


def path_ignored(path: str, ignore_globs: list[str]) -> bool:
    if not ignore_globs:
        return False
    p = path.replace("\\", "/")
    for pattern in ignore_globs:
        pattern = str(pattern).strip()
        if not pattern:
            continue
        if fnmatch.fnmatch(p, pattern) or fnmatch.fnmatch(p, pattern.rstrip("/") + "/*"):
            return True
        if pattern.endswith("/") and p.startswith(pattern):
            return True
        # directory prefix match, e.g. "dist" ignoring "dist/app.js"
        if fnmatch.fnmatch(os.path.basename(p), pattern):
            return True
    return False


def describe(rules: Rules) -> dict:
    """Compact, secret-free view of the effective rules (for the API surface)."""
    return {
        "source": rules.source,
        "max_comments": rules.max_comments,
        "min_severity": rules.min_severity,
        "max_files": rules.max_files,
        "verify": rules.verify,
        "verify_top_n": rules.verify_top_n,
        "consensus": rules.consensus,
        "skip_drafts": rules.skip_drafts,
        "skip_bot_prs": rules.skip_bot_prs,
        "skip_nits": rules.skip_nits,
        "max_rounds": rules.max_rounds,
        "converge_rounds": rules.converge_rounds,
        "linters": rules.linters,
        "post_check_run": rules.post_check_run,
        "check_run_conclusion": rules.check_run_conclusion,
        "required_status_check": rules.required_status_check,
        "ignore_paths": rules.ignore_paths,
        "focus": rules.focus,
        "custom_rules": rules.custom_rules,
    }
