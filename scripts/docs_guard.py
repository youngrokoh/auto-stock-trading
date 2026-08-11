#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (the script has no third-party dependencies):
#      uv run scripts/docs_guard.py check
# 3. It can also run with the system Python 3.14+:
#      python3 scripts/docs_guard.py check
# ──────────────────

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

INVENTORY_PATH: Final = Path("docs/generated/document-inventory.md")
CHANGE_MAP_PATH: Final = Path("docs/governance/change-map.yaml")
LINK_PATTERN: Final = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
STATUS_PATTERN: Final = re.compile(r"^- 상태:\s*(.+)$", re.MULTILINE)
WAIVER_PATTERN: Final = re.compile(r"^docs-not-required:\s*(\S.{9,})$", re.MULTILINE | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GuardError(Exception):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ChangeRule:
    name: str
    code_patterns: tuple[str, ...]
    document_paths: tuple[str, ...]


def normalized_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix().removeprefix("./")


def markdown_files(repo_root: Path) -> tuple[Path, ...]:
    docs_root = repo_root / "docs"
    return tuple(sorted(path for path in docs_root.rglob("*.md") if path.is_file()))


def parse_link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def check_links(repo_root: Path) -> None:
    documents = markdown_files(repo_root)
    failures: list[str] = []
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(text):
            target = parse_link_target(match.group(1))
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local_target = target.split("#", maxsplit=1)[0]
            if local_target and not (document.parent / local_target).resolve().exists():
                relative_document = document.relative_to(repo_root).as_posix()
                failures.append(f"{relative_document} -> {target}")
    if failures:
        details = "\n".join(f"  - {failure}" for failure in failures)
        raise GuardError(f"Broken local Markdown links:\n{details}")
    print(f"Links: {len(documents)} Markdown documents checked.")


def document_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return fallback


def document_status(text: str) -> str:
    match = STATUS_PATTERN.search(text)
    return match.group(1).strip() if match else "미지정"


def inventory_content(repo_root: Path) -> str:
    rows: list[str] = []
    for document in markdown_files(repo_root):
        relative = document.relative_to(repo_root)
        if relative == INVENTORY_PATH:
            continue
        text = document.read_text(encoding="utf-8")
        link = Path("..").joinpath(*relative.parts[1:]).as_posix()
        rows.append(
            f"| [{document_title(text, document.stem)}]({link}) | "
            f"`{relative.as_posix()}` | {document_status(text)} |"
        )
    return "\n".join(
        (
            "# 문서 인벤토리",
            "",
            "> 이 파일은 `python3 scripts/docs_guard.py generate`로 생성됩니다. 직접 수정하지 마세요.",
            "",
            "| 문서 | 경로 | 상태 |",
            "|---|---|---|",
            *rows,
            "",
        )
    )


def generate_inventory(repo_root: Path, *, check_only: bool) -> None:
    inventory = repo_root / INVENTORY_PATH
    expected = inventory_content(repo_root)
    current = inventory.read_text(encoding="utf-8") if inventory.exists() else ""
    if check_only:
        if current != expected:
            raise GuardError("Generated documentation is stale. Run: python3 scripts/docs_guard.py generate")
        print("Generated documentation: current.")
        return
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(expected, encoding="utf-8")
    print(f"Generated: {INVENTORY_PATH.as_posix()}")


def string_tuple(value: JsonValue, *, field: str, rule_name: str) -> tuple[str, ...]:
    match value:
        case list(items) if items:
            strings: list[str] = []
            for item in items:
                match item:
                    case str(text):
                        strings.append(text)
                    case _:
                        raise GuardError(f"Rule '{rule_name}' contains a non-string '{field}' value.")
            return tuple(strings)
        case _:
            raise GuardError(f"Rule '{rule_name}' must define a non-empty string list for '{field}'.")


def load_rules(repo_root: Path) -> tuple[ChangeRule, ...]:
    path = repo_root / CHANGE_MAP_PATH
    try:
        raw: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GuardError(f"Cannot read {CHANGE_MAP_PATH.as_posix()}: {error}") from error
    match raw:
        case {"version": 1, "rules": list(raw_rules)}:
            rules: list[ChangeRule] = []
            for raw_rule in raw_rules:
                match raw_rule:
                    case {"name": str(name), "code": code, "docs": docs}:
                        rules.append(
                            ChangeRule(
                                name,
                                string_tuple(code, field="code", rule_name=name),
                                string_tuple(docs, field="docs", rule_name=name),
                            )
                        )
                    case _:
                        raise GuardError("Each change-map rule must contain name, code, and docs fields.")
            parsed_rules = tuple(rules)
            missing_paths = sorted(
                document_path
                for rule in parsed_rules
                for document_path in rule.document_paths
                if not (repo_root / document_path).is_file()
            )
            if missing_paths:
                details = "\n".join(f"  - {path}" for path in missing_paths)
                raise GuardError(f"Mapped documents do not exist:\n{details}")
            return parsed_rules
        case _:
            raise GuardError("change-map.yaml must contain version 1 and a rules list.")


def changed_files_from_git(repo_root: Path, base_ref: str) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise GuardError(f"Cannot read Git changes from base ref '{base_ref}'.") from error
    return tuple(normalized_path(line) for line in result.stdout.splitlines() if line.strip())


def waiver_reason(candidate: str) -> str | None:
    match = WAIVER_PATTERN.search(candidate)
    if match:
        return match.group(1).strip()
    stripped = candidate.strip()
    return stripped if len(stripped) >= 10 and "\n" not in stripped else None


def check_drift(
    repo_root: Path,
    changed_files: tuple[str, ...],
    base_ref: str | None,
    waiver: str,
) -> None:
    changes = tuple(normalized_path(path) for path in changed_files)
    if not changes:
        if base_ref is None:
            raise GuardError("Provide --changed-file or --base-ref for the drift check.")
        changes = changed_files_from_git(repo_root, base_ref)
    missing: list[ChangeRule] = []
    for rule in load_rules(repo_root):
        code_changed = any(
            fnmatch.fnmatch(path, pattern)
            for path in changes
            for pattern in rule.code_patterns
        )
        docs_changed = any(path in rule.document_paths for path in changes)
        if code_changed and not docs_changed:
            missing.append(rule)
    if missing:
        reason = waiver_reason(waiver)
        if reason is not None:
            print(f"Documentation waiver accepted: {reason}")
            return
        details = "\n".join(
            f"  - {rule.name}: one of {', '.join(rule.document_paths)}"
            for rule in missing
        )
        raise GuardError(f"Documentation updates are missing:\n{details}")
    print(f"Drift: {len(changes)} changed paths satisfy the documentation map.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and verify project documentation.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("links", "generate", "check"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
        if command == "generate":
            command_parser.add_argument("--check", action="store_true")
    drift = subparsers.add_parser("drift")
    drift.add_argument("--repo-root", type=Path, default=Path.cwd())
    drift.add_argument("--changed-file", action="append", default=[])
    drift.add_argument("--base-ref")
    drift.add_argument("--waiver", default=os.environ.get("PR_BODY", ""))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root: Path = args.repo_root.resolve()
    try:
        match args.command:
            case "links":
                check_links(repo_root)
            case "generate":
                generate_inventory(repo_root, check_only=args.check)
            case "check":
                generate_inventory(repo_root, check_only=True)
                check_links(repo_root)
                load_rules(repo_root)
                print("Documentation guard: all checks passed.")
            case "drift":
                check_drift(repo_root, tuple(args.changed_file), args.base_ref, args.waiver)
            case unreachable:
                raise GuardError(f"Unsupported command: {unreachable}")
    except GuardError as error:
        print(f"docs-guard: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
