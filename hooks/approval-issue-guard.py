#!/usr/bin/env python3
"""Defense-in-depth warning for direct agent approval mutation commands.

The OS-owned helper and authority ledger are the identity boundary. This hook
reduces accidental attempts on shells that actually invoke it.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path


DENIAL = (
    "DENIED: live approval authority is OS-owned. Review the exact helper command, "
    "then run it with fresh sudo authentication in Alex's normal Terminal.\n"
)

RESTRICTED_SUBCOMMANDS = frozenset({"approval-issue", "approval-invalidate"})

BASH_TOOL_NAMES = frozenset(
    {
        "Bash",
        "bash",
        "exec_command",
        "functions.exec",
        "functions.exec_command",
    }
)
SHELL_NAMES = frozenset({"bash", "sh", "zsh"})
SHELL_SEPARATORS = frozenset({";", "&", "|", "\n", "(", ")", "{", "}"})
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
PYTHON_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?\Z")
MAX_NESTED_COMMANDS = 32
PYTHON_VALUE_OPTIONS = frozenset({"-W", "-X", "--check-hash-based-pycs"})
SHELL_VALUE_OPTIONS = frozenset({"--init-file", "--rcfile", "-o", "+o", "-O", "+O"})
TERMINAL_OPTIONS = frozenset({"--help", "--version"})
CONTROL_PREFIXES = frozenset({"if", "then", "elif", "else", "while", "until", "do"})

# argparse options which do not consume a following value. All other known
# operating-layer options do, so an option value cannot be mistaken for the
# positional subcommand.
FLAG_OPTIONS = frozenset({"--json", "--summary", "--na", "--add"})
VALUE_OPTIONS = frozenset(
    {
        "--claude-home",
        "--codex-home",
        "--projects-root",
        "--output-root",
        "--since-days",
        "--check-write",
        "--project",
        "--projects",
        "--goal",
        "--work-id",
        "--pathway",
        "--kind",
        "--evidence",
        "--gate",
        "--result",
        "--action",
        "--agent",
        "--reason",
        "--proof-id",
        "--proof-type",
        "--verified-by",
        "--verify-cmd",
        "--canary-target",
        "--reviewer",
        "--verdict",
        "--judge",
        "--counterfactual",
        "--note",
        "--recommendation-id",
        "--control-risk",
        "--control-id",
        "--control-status",
        "--target-pathways",
        "--stale-after-days",
        "--input",
        "--window-days",
        "--gate-target",
        "--tier",
        "--release-receipt",
        "--ticket-id",
        "--consumer",
    }
)

# Used only when shlex rejects malformed shell text. The match must begin at a
# command boundary and place the real runner before the restricted subcommand.
SUSPICIOUS_FALLBACK_RE = re.compile(
    r"(?:\A|&&|\|\||[;\n])\s*"
    r"(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*"
    r"(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*)?"
    r"(?:command\s+)?"
    r"(?:(?:\S*/)?python(?:\d+(?:\.\d+)*)?(?:\s+-\S+)*\s+)?"
    r"(?:\S*/)?operating-layer\.py\s+[^;\n]*\bapproval-(?:issue|invalidate)\b",
    re.DOTALL | re.IGNORECASE,
)


def _basename(value: str) -> str:
    return Path(value).name.casefold()


def _normalize_quote_prefixes(command: str) -> str:
    """Make literal Bash ANSI-C and locale quotes parse like ordinary quotes."""
    continued = command.replace("\\\r\n", "").replace("\\\n", "")
    return re.sub(r"\$(?=['\"])", "", continued)


def _could_contain_restricted_subcommand(command: str) -> bool:
    """Cheap prefilter which cannot reject a literal shell-joined subcommand."""
    dequoted = command.casefold().translate(str.maketrans("", "", "'\"\\"))
    return any(subcommand in dequoted for subcommand in RESTRICTED_SUBCOMMANDS)


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|\n()<>{}")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _newline_suffix(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith(("\n", "\r")):
        return line[-1]
    return ""


def _strip_heredoc_bodies(command: str) -> str:
    """Remove literal here-doc input so examples are not treated as commands."""
    lines = command.splitlines(keepends=True)
    rendered: list[str] = []
    index = 0
    while index < len(lines):
        declaration = lines[index]
        rendered.append(declaration)
        try:
            tokens = _shell_tokens(_normalize_quote_prefixes(declaration))
        except ValueError:
            index += 1
            continue

        delimiters: list[tuple[str, bool]] = []
        for token_index, token in enumerate(tokens[:-1]):
            if token != "<<":
                continue
            delimiter = tokens[token_index + 1]
            strip_tabs = delimiter.startswith("-")
            if strip_tabs:
                delimiter = delimiter[1:]
            if delimiter:
                delimiters.append((delimiter, strip_tabs))

        index += 1
        for delimiter, strip_tabs in delimiters:
            while index < len(lines):
                body_line = lines[index]
                candidate = body_line.rstrip("\r\n")
                if strip_tabs:
                    candidate = candidate.lstrip("\t")
                rendered.append(_newline_suffix(body_line))
                index += 1
                if candidate == delimiter:
                    break
    return "".join(rendered)


def _segments(tokens: list[str]):
    segment: list[str] = []
    for token in tokens:
        if token and all(char in SHELL_SEPARATORS for char in token):
            if segment:
                yield segment
                segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def _skip_assignments(tokens: list[str], index: int) -> int:
    while index < len(tokens) and ASSIGNMENT_RE.fullmatch(tokens[index]):
        index += 1
    return index


def _is_redirection(token: str) -> bool:
    return any(char in token for char in "<>") and all(
        char in "<>&" for char in token
    )


def _skip_shell_prefix(tokens: list[str], index: int) -> int:
    """Skip leading assignments and redirections before an executable."""
    while index < len(tokens):
        next_index = _skip_assignments(tokens, index)
        if next_index != index:
            index = next_index
            continue
        if (
            tokens[index].isdigit()
            and index + 1 < len(tokens)
            and _is_redirection(tokens[index + 1])
        ):
            index += 1
        if index < len(tokens) and _is_redirection(tokens[index]):
            index += 2
            continue
        break
    return index


def _unwrap_prefixes(tokens: list[str], index: int) -> int | None:
    """Return the executable index after common direct shell wrappers."""
    index = _skip_shell_prefix(tokens, index)
    while index < len(tokens):
        name = _basename(tokens[index])
        if tokens[index] == "!" or name in CONTROL_PREFIXES:
            index = _skip_shell_prefix(tokens, index + 1)
            continue
        if name == "env":
            return index
        if name == "command":
            index += 1
            if index < len(tokens) and tokens[index] in {"-v", "-V"}:
                return None
            while index < len(tokens) and tokens[index] in {"-p", "--"}:
                index += 1
            continue
        if name == "builtin":
            index = _skip_shell_prefix(tokens, index + 1)
            continue
        if name == "exec":
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                if tokens[index] == "-a":
                    index += 2
                else:
                    index += 1
            index = _skip_shell_prefix(tokens, index)
            continue
        if name == "time":
            index += 1
            while index < len(tokens) and tokens[index].startswith(("-", "+")):
                if tokens[index] in TERMINAL_OPTIONS:
                    return None
                if tokens[index] in {"-f", "--format", "-o", "--output"}:
                    index += 2
                else:
                    index += 1
            index = _skip_shell_prefix(tokens, index)
            continue
        if name == "nohup":
            index += 1
            if index < len(tokens) and tokens[index] in TERMINAL_OPTIONS:
                return None
            if index < len(tokens) and tokens[index] == "--":
                index += 1
            index = _skip_shell_prefix(tokens, index)
            continue
        if name == "nice":
            index += 1
            while index < len(tokens) and tokens[index].startswith(("-", "+")):
                option = tokens[index]
                if option in TERMINAL_OPTIONS:
                    return None
                if option in {"-n", "--adjustment"}:
                    index += 2
                else:
                    index += 1
            index = _skip_shell_prefix(tokens, index)
            continue
        break
    return _skip_shell_prefix(tokens, index)


def _env_command_tokens(tokens: list[str], env_index: int) -> list[str] | None:
    """Return the command argv after env options, expanding literal -S values."""
    arguments = list(tokens[env_index + 1 :])
    expansions = 0
    while True:
        index = 0
        while index < len(arguments):
            token = arguments[index]
            if ASSIGNMENT_RE.fullmatch(token):
                index += 1
                continue
            if token == "--":
                return arguments[index + 1 :]
            if token in {"-u", "--unset", "-C", "--chdir", "-P"}:
                index += 2
                continue

            split_value = None
            trailing_index = index + 1
            if token in {"-S", "--split-string"}:
                if trailing_index >= len(arguments):
                    return []
                split_value = arguments[trailing_index]
                trailing_index += 1
            elif token.startswith("--split-string="):
                split_value = token.split("=", 1)[1]

            if split_value is not None:
                expansions += 1
                if expansions > MAX_NESTED_COMMANDS:
                    return None
                try:
                    split_tokens = shlex.split(
                        _normalize_quote_prefixes(split_value), comments=False, posix=True,
                    )
                except ValueError:
                    return []
                arguments = split_tokens + arguments[trailing_index:]
                break
            if token.startswith("-"):
                index += 1
                continue
            return arguments[index:]
        else:
            return []


def _python_script_index(tokens: list[str], index: int) -> int | None:
    index += 1
    while index < len(tokens):
        token = tokens[index]
        if (token in {"-h", "--help", "-V", "--version"}
                or token.startswith(("-VV", "--help-"))):
            return None
        if token == "--":
            return index + 1
        if token in {"-c", "-m"} or token.startswith(("-c", "-m")):
            return None
        if token in PYTHON_VALUE_OPTIONS:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return index
    return None


def _operating_subcommand(arguments: list[str]) -> str:
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--":
            return arguments[index + 1] if index + 1 < len(arguments) else ""
        option = token.split("=", 1)[0]
        if option.startswith("--") and option not in FLAG_OPTIONS | VALUE_OPTIONS:
            matches = [known for known in FLAG_OPTIONS | VALUE_OPTIONS
                       if known.startswith(option)]
            if len(matches) != 1:
                return ""
            option = matches[0]
        if option in FLAG_OPTIONS:
            if "=" in token:
                return ""
            index += 1
            continue
        if option in VALUE_OPTIONS:
            index += 1 if "=" in token else 2
            continue
        if token.startswith("-"):
            return ""
        return token
    return ""


def _segment_issues(tokens: list[str], depth: int) -> bool:
    index = _unwrap_prefixes(tokens, 0)
    if index is None or index >= len(tokens):
        return False

    executable = _basename(tokens[index])
    if executable == "env":
        nested_tokens = _env_command_tokens(tokens, index)
        if nested_tokens is None or depth >= MAX_NESTED_COMMANDS:
            return True
        if not nested_tokens:
            return False
        return _segment_issues(nested_tokens, depth + 1)

    if executable in SHELL_NAMES:
        option_index = index + 1
        while option_index < len(tokens) - 1:
            option = tokens[option_index]
            if option in TERMINAL_OPTIONS:
                return False
            if option in SHELL_VALUE_OPTIONS:
                option_index += 2
                continue
            if option.startswith(("-O", "+O")) and len(option) > 2:
                option_index += 1
                continue
            if option == "--command" or (
                option.startswith("-")
                and not option.startswith("--")
                and "c" in option[1:]
            ):
                if depth >= MAX_NESTED_COMMANDS:
                    return True
                return command_changes_approval_authority(tokens[option_index + 1], depth + 1)
            if option == "--" or not option.startswith(("-", "+")):
                return False
            option_index += 1
        return False

    script_index = index
    if PYTHON_RE.fullmatch(executable):
        script_index = _python_script_index(tokens, index)
        if script_index is None or script_index >= len(tokens):
            return False

    if _basename(tokens[script_index]) != "operating-layer.py":
        return False
    return _operating_subcommand(tokens[script_index + 1 :]) in RESTRICTED_SUBCOMMANDS


def command_changes_approval_authority(command: str, depth: int = 0) -> bool:
    normalized = _normalize_quote_prefixes(command)
    if not _could_contain_restricted_subcommand(normalized):
        return False
    normalized = _strip_heredoc_bodies(normalized)
    if not _could_contain_restricted_subcommand(normalized):
        return False
    try:
        tokens = _shell_tokens(normalized)
    except ValueError:
        return bool(SUSPICIOUS_FALLBACK_RE.search(normalized))
    return any(_segment_issues(segment, depth) for segment in _segments(tokens))


def main() -> int:
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or data.get("tool_name") not in BASH_TOOL_NAMES:
            return 0
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        commands = [
            tool_input[key]
            for key in ("command", "cmd")
            if isinstance(tool_input.get(key), str)
        ]
        if not any(command_changes_approval_authority(command) for command in commands):
            return 0
    except Exception:
        return 0

    sys.stderr.write(DENIAL)
    return 2


if __name__ == "__main__":
    sys.exit(main())
