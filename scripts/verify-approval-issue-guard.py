#!/usr/bin/env python3
"""Verify approval-issue guard wiring without invoking the approval CLI."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
DEFAULT_REPO_HOOK = REPO / "hooks" / "approval-issue-guard.py"
DEFAULT_CLAUDE_HOOK = Path.home() / ".claude" / "hooks" / "approval-issue-guard.py"
DEFAULT_CODEX_HOOK = Path.home() / ".codex" / "hooks" / "approval-issue-guard.py"
DEFAULT_CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
DEFAULT_CODEX_SETTINGS = Path.home() / ".codex" / "hooks.json"
DEFAULT_ISOLATED_SETTINGS = (
    Path.home() / ".claude" / "glm-routing" / "claude-config" / "settings.json"
)


def default_output_root() -> Path:
    configured = os.environ.get("OPERATING_LAYER_OUTPUT_ROOT")
    if configured:
        return Path(configured).expanduser()
    legacy = Path.home() / "Projects" / "memory-vault"
    if (legacy / "operator-intelligence").exists():
        return legacy
    return Path.home() / ".pathway-operating-layer"


DEFAULT_LEDGER = default_output_root() / "operator-intelligence" / "approvals.ndjson"
DENIAL = (
    "DENIED: approval-issue is reserved for Alex. "
    "Review the exact command, then run it in a normal Terminal.\n"
)

BLOCKED_FIXTURES = (
    ("command", "operating-layer.py approval-issue --help"),
    ("cmd", "python3 scripts/operating-layer.py approval-issue --help"),
    ("command", "TEST_ONLY=1 operating-layer.py approval-issue --help"),
    ("command", "sh -c 'operating-layer.py approval-issue --help'"),
    (
        "command",
        "python3 --check-hash-based-pycs always "
        "scripts/operating-layer.py approval-issue --help",
    ),
)
ALLOWED_FIXTURES = (
    "operating-layer.py pathway-next --help",
    "operating-layer.py --help",
    "rg 'approval-issue' hooks scripts",
    "printf '%s\\n' 'operating-layer.py approval-issue --help'",
)


def absolute_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else path.absolute()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--repo-hook", default=str(DEFAULT_REPO_HOOK))
    result.add_argument("--claude-hook", default=str(DEFAULT_CLAUDE_HOOK))
    result.add_argument("--codex-hook", default=str(DEFAULT_CODEX_HOOK))
    result.add_argument("--claude-settings", default=str(DEFAULT_CLAUDE_SETTINGS))
    result.add_argument("--codex-settings", default=str(DEFAULT_CODEX_SETTINGS))
    result.add_argument("--isolated-settings", default=str(DEFAULT_ISOLATED_SETTINGS))
    result.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    result.add_argument("--runs", type=int, default=120)
    return result


def load_json(path: Path, label: str, failures: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"{label} must be valid JSON: {exc}")
        return None


def check_settings(
    path: Path,
    label: str,
    expected_command: str,
    failures: list[str],
) -> None:
    data = load_json(path, label, failures)
    if not isinstance(data, dict):
        if data is not None:
            failures.append(f"{label} must contain a JSON object")
        return
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        failures.append(f"{label} must contain a hooks object")
        return
    pre_tool = hooks.get("PreToolUse")
    if not isinstance(pre_tool, list):
        failures.append(f"{label} must contain hooks.PreToolUse")
        return
    bash_matchers = [entry for entry in pre_tool if isinstance(entry, dict)
                     and entry.get("matcher") == "Bash"]
    if len(bash_matchers) != 1:
        failures.append(f"{label} must contain exactly one Bash matcher")
        return
    handlers = bash_matchers[0].get("hooks")
    if not isinstance(handlers, list):
        failures.append(f"{label} Bash matcher must contain a hooks list")
        return
    expected = {"type": "command", "command": expected_command, "timeout": 5}
    matches = [index for index, handler in enumerate(handlers) if handler == expected]
    if len(matches) != 1:
        failures.append(f"{label} Bash matcher must contain exactly one exact guard entry")
        return
    if matches[0] != len(handlers) - 1:
        failures.append(f"{label} guard entry must be last in its Bash matcher")


def check_symlink(installed: Path, tracked: Path, label: str, failures: list[str]) -> bool:
    if not installed.is_symlink():
        failures.append(f"{label} must be a symlink to the tracked source")
        return False
    try:
        target = installed.resolve(strict=True)
        canonical = tracked.resolve(strict=True)
    except OSError as exc:
        failures.append(f"{label} must resolve to the tracked source: {exc}")
        return False
    if target != canonical:
        failures.append(f"{label} must resolve to the tracked source {canonical}; got {target}")
        return False
    return True


def run_hook(hook: Path, raw_input: str) -> tuple[subprocess.CompletedProcess, float]:
    started = time.perf_counter_ns()
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=raw_input,
        capture_output=True,
        text=True,
        timeout=5,
    )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return proc, elapsed_ms


def hook_payload(field: str, command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {field: command}})


def check_fixtures(hooks: tuple[Path, ...], failures: list[str]) -> tuple[int, int]:
    blocked_count = 0
    allowed_count = 0
    for hook in hooks:
        for field, command in BLOCKED_FIXTURES:
            try:
                proc, _ = run_hook(hook, hook_payload(field, command))
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(f"blocked fixture could not run through {hook}: {exc}")
                continue
            if proc.returncode != 2 or proc.stdout != "" or proc.stderr != DENIAL:
                failures.append(
                    f"blocked fixture failed through {hook}: rc={proc.returncode}, "
                    f"stdout={proc.stdout!r}, stderr={proc.stderr!r}"
                )
            else:
                blocked_count += 1
        for command in ALLOWED_FIXTURES:
            try:
                proc, _ = run_hook(hook, hook_payload("command", command))
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(f"allowed fixture could not run through {hook}: {exc}")
                continue
            if proc.returncode != 0 or proc.stdout != "" or proc.stderr != "":
                failures.append(
                    f"allowed fixture failed through {hook}: rc={proc.returncode}, "
                    f"stdout={proc.stdout!r}, stderr={proc.stderr!r}"
                )
            else:
                allowed_count += 1
    return blocked_count, allowed_count


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    failures: list[str] = []
    if args.runs < 1:
        failures.append("--runs must be at least 1")

    repo_hook = absolute_path(args.repo_hook)
    claude_hook = absolute_path(args.claude_hook)
    codex_hook = absolute_path(args.codex_hook)
    claude_settings = absolute_path(args.claude_settings)
    codex_settings = absolute_path(args.codex_settings)
    isolated_settings = absolute_path(args.isolated_settings)
    ledger = absolute_path(args.ledger)

    try:
        ledger_before = ledger.read_bytes()
    except OSError as exc:
        ledger_before = None
        failures.append(f"ledger must be readable: {exc}")

    claude_link_valid = check_symlink(
        claude_hook, repo_hook, "Claude installed hook", failures,
    )
    codex_link_valid = check_symlink(
        codex_hook, repo_hook, "Codex installed hook", failures,
    )
    check_settings(
        claude_settings,
        "Claude settings",
        f"python3 {claude_hook}",
        failures,
    )
    check_settings(
        codex_settings,
        "Codex settings",
        f"python3 {codex_hook}",
        failures,
    )
    check_settings(
        isolated_settings,
        "isolated GLM/Kimi settings",
        f"python3 {claude_hook}",
        failures,
    )

    fixture_hooks = (repo_hook, claude_hook, codex_hook) if (
        claude_link_valid and codex_link_valid
    ) else (repo_hook,)
    blocked_count, allowed_count = check_fixtures(fixture_hooks, failures)

    timings: list[float] = []
    if args.runs > 0:
        timing_input = hook_payload("command", "true")
        for _ in range(args.runs):
            try:
                proc, elapsed_ms = run_hook(repo_hook, timing_input)
            except (OSError, subprocess.SubprocessError) as exc:
                failures.append(f"timing fixture could not run: {exc}")
                break
            if proc.returncode != 0 or proc.stdout != "" or proc.stderr != "":
                failures.append("timing fixture must return 0 without output")
                break
            timings.append(elapsed_ms)

    p95_ms = percentile_95(timings) if timings else None
    if p95_ms is not None and p95_ms >= 50:
        failures.append(f"hook p95 must be below 50ms; got {p95_ms:.2f}ms")

    try:
        ledger_after = ledger.read_bytes()
    except OSError as exc:
        ledger_after = None
        failures.append(f"ledger must remain readable: {exc}")
    ledger_unchanged = ledger_before is not None and ledger_after == ledger_before
    if not ledger_unchanged:
        failures.append("ledger bytes changed during guard verification")
    ledger_sha256 = hashlib.sha256(ledger_before).hexdigest() if ledger_before is not None else None
    ledger_line_count = len(ledger_before.splitlines()) if ledger_before is not None else None

    summary = {
        "status": "fail" if failures else "pass",
        "run_count": args.runs,
        "settings_checked": 3,
        "symlinks_checked": 2,
        "blocked_fixtures": blocked_count,
        "allowed_fixtures": allowed_count,
        "p95_ms": round(p95_ms, 3) if p95_ms is not None else None,
        "ledger_unchanged": ledger_unchanged,
        "ledger_sha256": ledger_sha256,
        "ledger_line_count": ledger_line_count,
        "failures": failures,
    }
    print(json.dumps(summary, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
