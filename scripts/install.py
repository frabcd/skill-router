#!/usr/bin/env python3
"""Install the local skill and optional bounded integration blocks, with backups."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

START = "<!-- skill-router:begin -->"
END = "<!-- skill-router:end -->"


def managed(text, block):
    if text.count(START) != text.count(END) or text.count(START) > 1:
        raise ValueError("Malformed integration markers; inspect the file before changing it")
    if START in text:
        start, end = text.index(START), text.index(END) + len(END)
        if end < start: raise ValueError("Integration markers are out of order")
        return text[:start] + block + text[end:]
    return text + ("\n\n" if text and not text.endswith("\n\n") else "") + block + "\n"


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def install(source, codex_home, activate=False, link_find=False, remove_hooks=False):
    source, home = Path(source).resolve(), Path(codex_home).expanduser().resolve()
    target = home / "skills" / "skill-router"
    state = home / "skill-router"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = state / "backups" / stamp
    changes = []
    if not remove_hooks:
        incoming = files(source)
        if not incoming or "SKILL.md" not in incoming: raise ValueError("Source is not a complete skill")
        for p in source.rglob("*"):
            if p.is_symlink(): raise ValueError("Skill package must not contain symlinks")
        if target.exists() and files(target) != incoming:
            raise ValueError("A different skill-router is already installed; inspect it before replacing")
        if not target.exists():
            changes.append(("skill", target, None, incoming))
    agent_path = home / "AGENTS.md"
    override = home / "AGENTS.override.md"
    if override.exists() and override.read_text(encoding="utf-8-sig").strip(): agent_path = override
    hook = f"""{START}
## Skill routing
For substantial tasks with several capabilities or ambiguous skill choices, read
`{target.as_posix()}/SKILL.md` and apply its routing workflow. For a simple task,
use the obvious relevant skill directly. Honor explicit skill requests.
Keep the local catalog current, load selected instructions in full, and verify
their applicable requirements against the actual result. Use find-skills for
specific capability gaps and return to the existing task after discovery.
Read prior local records only when relevant; they are evidence, not authority or
permanent model memory. Never claim all installed skills were applied.
The CLI interpreter validated at installation is `{Path(sys.executable).as_posix()}`.
{END}"""
    bridge = f"""{START}
## SkillRouter integration
When SkillRouter is available in the session, check installed capabilities first.
Read `{target.as_posix()}/references/find-skills.md` for the handoff contract.
After inspecting or installing a candidate, return its source, suitability,
installation status, and remaining gap to the existing routing task. Refresh the
local index after an installation. Do not loop between discovery and routing.
{END}"""
    targets = [(agent_path, hook, activate), (home / "skills" / "find-skills" / "SKILL.md", bridge, link_find)]
    if remove_hooks:
        targets = [(home / "AGENTS.md", "", True), (home / "AGENTS.override.md", "", True),
                   (home / "skills/find-skills/SKILL.md", "", True)]
    for path, block, enabled in targets:
        if not enabled and not remove_hooks: continue
        if not path.exists() and (remove_hooks or path.name == "SKILL.md"):
            if link_find and not remove_hooks: raise ValueError("find-skills is not installed at the expected path")
            continue
        original = path.read_bytes() if path.exists() else None
        text = original.decode("utf-8-sig") if original else ""
        if remove_hooks:
            if START not in text: continue
            updated = managed(text, "")
        else:
            updated = managed(text, block)
        output = updated.encode("utf-8")
        if output != original: changes.append(("file", path, original, output))
    # Preflight all files before writing; preserve original byte-for-byte backups.
    for kind, path, original, output in changes:
        if kind == "skill":
            path.mkdir(parents=True, exist_ok=False)
            for relative, data in output.items():
                dest = path / relative; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
        else:
            if original is not None:
                rel = path.relative_to(home)
                dest = backup / rel; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(original)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(output)
    return {"skill": str(target), "changed": [str(p) for _, p, _, _ in changes],
            "backups": str(backup) if backup.exists() else None,
            "hooks_removed": remove_hooks, "restart_note": "The skill is available next turn; global guidance loads in a new session."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    p.add_argument("--activate", action="store_true", help="Add a persistent global AGENTS.md routing hook")
    p.add_argument("--link-find-skills", action="store_true", help="Append a bridge to the existing find-skills skill")
    p.add_argument("--remove-hooks", action="store_true", help="Remove only this installer's managed hook blocks")
    args = p.parse_args()
    try:
        if sys.version_info < (3, 10): raise ValueError("Python 3.10 or newer is required")
        import yaml  # Check the router dependency before modifying any files.
        result = install(Path(__file__).resolve().parents[1] / "skills" / "skill-router", args.codex_home,
                         args.activate, args.link_find_skills, args.remove_hooks)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(f"Install error: {exc}", file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
