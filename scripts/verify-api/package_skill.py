#!/usr/bin/env python3
"""
将 Skill 目录打包为可分发 .skill 文件（ZIP）。

业务方可直接运行，无额外 Python 依赖（仅用标准库）：

  python3 scripts/verify-api/package_skill.py scripts/verify-api/invoice-test-check ./
  python3 scripts/verify-api/package_skill.py /path/to/my-skill ./dist

输出：{output-dir}/{skill-folder-name}.skill
"""

from __future__ import annotations

import fnmatch
import re
import sys
import zipfile
from pathlib import Path

EXCLUDE_DIRS = {"__pycache__", "node_modules", ".git"}
EXCLUDE_GLOBS = ("*.pyc",)
EXCLUDE_FILES = {".DS_Store"}
ROOT_EXCLUDE_DIRS = {"evals"}

ALLOWED_FRONTMATTER_KEYS = frozenset(
    {"name", "description", "license", "allowed-tools", "metadata", "compatibility"}
)


def validate_skill(skill_path: Path) -> tuple[bool, str]:
    """Basic SKILL.md validation (stdlib only, aligned with skill-creator quick_validate)."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False, "No YAML frontmatter found"

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return False, "Invalid frontmatter format (need ---\\n...\\n---)"

    frontmatter = match.group(1)

    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
    if not name_match:
        return False, "Missing 'name' in frontmatter"
    if not desc_match:
        return False, "Missing 'description' in frontmatter"

    name = name_match.group(1).strip().strip("'\"")
    description = desc_match.group(1).strip().strip("'\"")

    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if key and key not in ALLOWED_FRONTMATTER_KEYS:
            return False, (
                f"Unexpected key '{key}' in frontmatter. "
                f"Allowed: {', '.join(sorted(ALLOWED_FRONTMATTER_KEYS))}"
            )

    if not re.match(r"^[a-z0-9-]+$", name):
        return False, f"Name '{name}' must be kebab-case (lowercase, digits, hyphens)"
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return False, f"Name '{name}' has invalid hyphen placement"
    if len(name) > 64:
        return False, f"Name too long ({len(name)} chars, max 64)"

    if "<" in description or ">" in description:
        return False, "Description cannot contain angle brackets"
    if len(description) > 1024:
        return False, f"Description too long ({len(description)} chars, max 1024)"

    folder_name = skill_path.name
    if name != folder_name:
        return False, f"Frontmatter name '{name}' must match folder name '{folder_name}'"

    return True, "Skill is valid!"


def should_exclude(rel_path: Path) -> bool:
    parts = rel_path.parts
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True
    if rel_path.name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(rel_path.name, pat) for pat in EXCLUDE_GLOBS)


def package_skill(skill_path: Path, output_dir: Path | None = None) -> Path | None:
    skill_path = skill_path.resolve()
    if not skill_path.is_dir():
        print(f"Error: not a directory: {skill_path}", file=sys.stderr)
        return None

    print("Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"Validation failed: {message}", file=sys.stderr)
        return None
    print(f"OK: {message}\n")

    out_dir = (output_dir or Path.cwd()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{skill_path.name}.skill"

    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in skill_path.rglob("*"):
                if not file_path.is_file():
                    continue
                arcname = file_path.relative_to(skill_path.parent)
                if should_exclude(arcname):
                    print(f"  skipped: {arcname}")
                    continue
                zf.write(file_path, arcname)
                print(f"  added: {arcname}")
    except OSError as exc:
        print(f"Error creating .skill file: {exc}", file=sys.stderr)
        return None

    print(f"\nPackaged: {archive}")
    return archive


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 package_skill.py <path/to/skill-folder> [output-directory]\n"
            "\nExample:\n"
            "  python3 scripts/verify-api/package_skill.py scripts/verify-api/invoice-test-check ./\n"
            "  python3 scripts/verify-api/package_skill.py /path/to/invoice-test-check ./dist",
            file=sys.stderr,
        )
        sys.exit(1)

    skill_arg = Path(sys.argv[1])
    output_arg = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    print(f"Packaging: {skill_arg}")
    if output_arg:
        print(f"Output dir: {output_arg}")
    print()

    result = package_skill(skill_arg, output_arg)
    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
