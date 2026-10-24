#!/usr/bin/env python3
"""Local catalog, transparent candidate retrieval, and evidence ledger. No network."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

try:
    import yaml
except ImportError:
    raise SystemExit("PyYAML is required: python -m pip install 'PyYAML>=6.0,<7'")

MAX_TEXT = 512_000
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}
STOP = set("a an the to of for and or in on with use using when skill skills user task this that from is are be it as by".split())


class RouterError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def text_file(path):
    path = Path(path)
    if path.stat().st_size > MAX_TEXT:
        raise RouterError(f"Instruction file exceeds {MAX_TEXT} bytes: {path}")
    return path.read_text(encoding="utf-8-sig")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".router-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RouterError(f"Cannot read state {path}: {exc}") from exc


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def metadata(path):
    text = text_file(path)
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", text, re.S)
    if not match:
        raise RouterError("Missing YAML frontmatter")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise RouterError("Frontmatter must be a mapping")
    for key in ("name", "description"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise RouterError(f"Missing text {key}")
    return data


def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def resource(entry, relative="SKILL.md"):
    root = Path(entry["path"]).parent.resolve()
    requested = Path(relative)
    if requested.is_absolute() or ".." in requested.parts:
        raise RouterError("Resource must be a relative path within the selected skill")
    target = (root / requested).resolve()
    if not inside(target, root) or not target.is_file():
        raise RouterError(f"Resource missing or escapes skill directory: {relative}")
    return target


def build_index(roots):
    entries, errors, seen = [], [], set()
    for supplied in roots:
        root = Path(supplied).expanduser().resolve()
        if not root.is_dir():
            errors.append({"path": str(root), "error": "Root is unavailable"})
            continue
        def walk_error(exc):
            errors.append({"path": str(exc.filename), "error": str(exc)})
        for base, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(base) / d).is_symlink())
            if "SKILL.md" not in files:
                continue
            path = (Path(base) / "SKILL.md").resolve()
            if str(path) in seen:
                continue
            seen.add(str(path))
            try:
                if not inside(path, root):
                    raise RouterError("Symlink escapes the configured root")
                data = metadata(path)
                implicit = True
                policy_file = path.parent / "agents" / "openai.yaml"
                if policy_file.exists():
                    if not inside(policy_file, path.parent):
                        raise RouterError("Invocation policy escapes skill directory")
                    policy = yaml.safe_load(text_file(policy_file)) or {}
                    if not isinstance(policy, dict):
                        raise RouterError("Invocation metadata must be a mapping")
                    invocation = policy.get("policy", {})
                    if not isinstance(invocation, dict):
                        raise RouterError("Invocation policy must be a mapping")
                    implicit = invocation.get("allow_implicit_invocation", True)
                    if not isinstance(implicit, bool):
                        raise RouterError("allow_implicit_invocation must be a boolean")
                entries.append({
                    "id": data["name"] + "@" + digest(str(path).encode())[:12],
                    "name": data["name"], "description": data["description"].strip(),
                    "path": str(path), "root": str(root), "sha256": file_hash(path),
                    "implicit": implicit,
                })
            except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
                errors.append({"path": str(path), "error": str(exc)})
    entries.sort(key=lambda item: (item["name"].casefold(), item["path"]))
    return {"schema": 1, "indexed_at": now(), "roots": [str(Path(r).expanduser().resolve()) for r in roots],
            "skills": entries, "errors": errors}


def resolve(entries, name):
    matches = [e for e in entries if e["id"] == name]
    if not matches:
        matches = [e for e in entries if e["name"] == name]
    if len(matches) != 1:
        raise RouterError(f"Expected one skill for {name!r}; matches: {[e['id'] for e in matches]}")
    return matches[0]


def tokens(text):
    return {t for t in re.findall(r"[\w]+", text.casefold()) if t not in STOP and len(t) > 1}


def rank(entries, query, required=(), excluded=(), limit=6):
    required_ids = {resolve(entries, name)["id"] for name in required}
    excluded_ids = {resolve(entries, name)["id"] for name in excluded}
    if required_ids & excluded_ids:
        raise RouterError("A skill cannot be both required and excluded")
    q = tokens(query)
    documents = [tokens(e["name"] + " " + e["description"]) for e in entries]
    frequencies = {term: sum(term in doc for doc in documents) for term in q}
    results = []
    for entry, document in zip(entries, documents):
        explicit = entry["id"] in required_ids
        if entry["id"] in excluded_ids or (not entry["implicit"] and not explicit):
            continue
        overlap = q & document
        score = sum(math.log(1 + len(entries) / (1 + frequencies[t])) for t in overlap)
        score += 2 * len(q & tokens(entry["name"]))
        if not overlap and not explicit:
            continue
        results.append({**entry, "score": round(score, 3), "explicit": explicit,
                        "matched_terms": sorted(overlap), "status": "candidate"})
    results.sort(key=lambda r: (-int(r["explicit"]), -r["score"], r["id"]))
    # Never discard an explicitly requested capability because of the shortlist limit.
    return results[:max(limit, len(required_ids))]


def run_path(state, run_id):
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise RouterError("Run ID must be the 32-character ID returned by begin")
    return Path(state) / "runs" / (run_id + ".json")


def save_run(state, run):
    run["updated_at"] = now()
    write_json(run_path(state, run["id"]), run)


def begin(state, catalog, task, selections):
    selected, ids = [], set()
    for selection in selections:
        name, separator, purpose = selection.partition("::")
        if not separator or not purpose.strip():
            raise RouterError("Use --select 'skill-name-or-id::concrete purpose'")
        entry = resolve(catalog["skills"], name)
        if entry["id"] in ids:
            raise RouterError("A skill was selected twice")
        if file_hash(entry["path"]) != entry["sha256"]:
            raise RouterError("Catalog source changed; run index again")
        ids.add(entry["id"])
        selected.append({**entry, "purpose": purpose.strip(), "loads": {}, "criteria": []})
    if not selected or not task.strip():
        raise RouterError("A non-empty task label and selected skill are required")
    run = {"schema": 1, "id": uuid4().hex, "task": task.strip(), "created_at": now(),
           "status": "in-progress", "skills": selected, "notes": []}
    save_run(state, run)
    return run


def changed(path, expected):
    try:
        return file_hash(path) != expected
    except OSError:
        return True


def record_load(entry, relative):
    target = resource(entry, relative)
    content = text_file(target)
    previous = entry["loads"].get(relative)
    current = file_hash(target)
    if previous and previous["sha256"] != current:
        for criterion in entry["criteria"]:
            if criterion["source"] == relative:
                criterion["status"] = "pending"
                criterion["evidence"] = None
    entry["loads"][relative] = {"sha256": current, "emitted_at": now(), "acknowledged": None}
    return content


def acknowledge(entry, relative, summary):
    receipt = entry["loads"].get(relative)
    if not receipt or changed(resource(entry, relative), receipt["sha256"]):
        raise RouterError("Load the current resource before acknowledging it")
    if len(summary.strip()) < 10:
        raise RouterError("Supply a concrete application summary (at least 10 characters)")
    receipt["acknowledged"] = {"at": now(), "application": summary.strip(), "type": "agent-attestation"}


def add_criterion(entry, relative, quote, check, replace=None, reason=None):
    receipt = entry["loads"].get(relative)
    target = resource(entry, relative)
    if not receipt or not receipt["acknowledged"] or changed(target, receipt["sha256"]):
        raise RouterError("Load and acknowledge the current source before creating a criterion")
    if not 10 <= len(quote.strip()) <= 500 or quote not in text_file(target):
        raise RouterError("Quote must be an exact 10-500 character excerpt from the source")
    if len(check.strip()) < 10:
        raise RouterError("Describe an observable check (at least 10 characters)")
    criterion = {"id": uuid4().hex[:12], "source": relative, "source_sha256": receipt["sha256"],
                 "quote": quote, "check": check.strip(), "status": "pending", "evidence": None, "history": []}
    if replace:
        previous = [c for c in entry["criteria"] if c["id"] == replace]
        if len(previous) != 1 or not reason or len(reason.strip()) < 10:
            raise RouterError("Replacing a criterion needs its ID and a concrete reason")
        criterion["supersedes"] = {"reason": reason, "criterion": previous[0]}
        entry["criteria"][entry["criteria"].index(previous[0])] = criterion
    else:
        entry["criteria"].append(criterion)
    return criterion


def record_evidence(criterion, status, observation, artifact=None):
    if status not in {"pass", "fail", "blocked"} or len(observation.strip()) < 10:
        raise RouterError("Use pass/fail/blocked and a concrete observation (at least 10 characters)")
    evidence = {"at": now(), "observation": observation.strip(), "type": "agent-attestation"}
    if artifact:
        path = Path(artifact).expanduser().resolve()
        if not path.is_file():
            raise RouterError("Evidence artifact must be an existing file")
        evidence["artifact"] = {"path": str(path), "sha256": file_hash(path)}
    criterion["history"].append({"status": status, "evidence": evidence})
    criterion["status"], criterion["evidence"] = status, evidence


def verify(run):
    failures = []
    if not run.get("skills"):
        failures.append("No selected skills")
    for entry in run["skills"]:
        prefix = entry["id"]
        if "SKILL.md" not in entry["loads"]:
            failures.append(f"{prefix}: SKILL.md was not loaded")
        for relative, receipt in entry["loads"].items():
            try:
                stale = changed(resource(entry, relative), receipt["sha256"])
            except (OSError, RouterError):
                stale = True
            if stale:
                failures.append(f"{prefix}: stale resource {relative}")
            if not receipt["acknowledged"]:
                failures.append(f"{prefix}: {relative} was not acknowledged")
        if not entry["criteria"]:
            failures.append(f"{prefix}: no criteria")
        for criterion in entry["criteria"]:
            label = f"{prefix}/{criterion['id']}"
            try:
                target = resource(entry, criterion["source"])
                if changed(target, criterion["source_sha256"]) or criterion["quote"] not in text_file(target):
                    failures.append(f"{label}: source changed; replace the criterion with a current contract")
            except (OSError, RouterError):
                failures.append(f"{label}: source unavailable")
            if criterion["status"] != "pass" or not criterion["evidence"]:
                failures.append(f"{label}: {criterion['status']}")
            evidence = criterion["evidence"] or {}
            artifact = evidence.get("artifact")
            if artifact and changed(artifact["path"], artifact["sha256"]):
                failures.append(f"{label}: evidence artifact changed or disappeared")
    return {"run": run["id"], "verified": not failures, "failures": failures,
            "meaning": "Record completeness/freshness only; evidence assertions require review."}


def history(state):
    results = []
    for path in sorted((Path(state) / "runs").glob("*.json")):
        results.append(read_json(path))
    return sorted(results, key=lambda r: r["updated_at"], reverse=True)


def coverage(catalog, runs):
    rows = []
    for entry in catalog["skills"]:
        uses = [(run, selected) for run in runs for selected in run["skills"] if selected["id"] == entry["id"]]
        rows.append({"id": entry["id"], "name": entry["name"], "indexed": True,
                     "catalog_current": not changed(entry["path"], entry["sha256"]),
                     "selected_runs": len(uses),
                     "loaded_runs": sum("SKILL.md" in s["loads"] for _, s in uses),
                     "acknowledged_runs": sum(bool(s["loads"].get("SKILL.md", {}).get("acknowledged")) for _, s in uses),
                     "verified_runs": sum(r["status"] == "verified" and verify(r)["verified"] for r, _ in uses)})
    return rows


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default=str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skill-router"))
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("index"); s.add_argument("--root", action="append", default=[])
    sub.add_parser("list")
    s = sub.add_parser("rank"); s.add_argument("query"); s.add_argument("--require", action="append", default=[]); s.add_argument("--exclude", action="append", default=[]); s.add_argument("--limit", type=int, default=6)
    s = sub.add_parser("begin"); s.add_argument("--task", required=True); s.add_argument("--select", action="append", required=True)
    for command in ("load", "ack", "criterion", "evidence", "note", "verify"):
        s = sub.add_parser(command); s.add_argument("run")
        if command in {"load", "ack", "criterion", "evidence"}:
            s.add_argument("skill")
        if command in {"load", "ack", "criterion"}:
            s.add_argument("--resource", default="SKILL.md")
        if command == "ack": s.add_argument("--summary", required=True)
        if command == "criterion":
            s.add_argument("--quote", required=True); s.add_argument("--check", required=True)
            s.add_argument("--replace"); s.add_argument("--reason")
        if command == "evidence":
            s.add_argument("criterion"); s.add_argument("--status", choices=["pass", "fail", "blocked"], required=True); s.add_argument("--observation", required=True); s.add_argument("--artifact")
        if command == "note": s.add_argument("text")
    s = sub.add_parser("recall"); s.add_argument("--skill"); s.add_argument("--limit", type=int, default=5)
    sub.add_parser("coverage")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    state = Path(args.state).expanduser().resolve()
    catalog_path = state / "catalog.json"
    try:
        if args.command == "index":
            roots = args.root
            if not roots and catalog_path.exists(): roots = read_json(catalog_path)["roots"]
            if not roots:
                home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
                roots = [str(p) for p in (home / "skills", Path.home() / ".agents" / "skills", Path.cwd() / ".agents" / "skills") if p.is_dir()]
            catalog = build_index(roots)
            write_json(catalog_path, catalog)
            emit({"indexed": len(catalog["skills"]), "errors": catalog["errors"], "catalog": str(catalog_path)})
            return 0 if catalog["skills"] else 1
        if args.command in {"list", "rank", "begin", "coverage"}:
            catalog = read_json(catalog_path)
        if args.command == "list": emit(catalog); return 0
        if args.command == "rank":
            if args.limit < 1: raise RouterError("--limit must be positive")
            emit({"candidates": rank(catalog["skills"], args.query, args.require, args.exclude, args.limit), "decision": "Agent must assess semantics, exclusions, prerequisites and enabled status."}); return 0
        if args.command == "begin":
            run = begin(state, catalog, args.task, args.select); emit({"run": run["id"], "path": str(run_path(state, run["id"]))}); return 0
        if args.command == "coverage": emit(coverage(catalog, history(state))); return 0
        if args.command == "recall":
            if args.limit < 1: raise RouterError("--limit must be positive")
            runs = history(state)
            if args.skill: runs = [r for r in runs if any(args.skill in {s["name"], s["id"]} for s in r["skills"])]
            emit([{**r, "current_validation": verify(r)} for r in runs[:args.limit]]); return 0
        run = read_json(run_path(state, args.run))
        entry = resolve(run["skills"], args.skill) if hasattr(args, "skill") else None
        output = None
        if args.command == "load":
            content = record_load(entry, args.resource)
            print(f"--- Skill resource: {entry['id']} / {args.resource} ---\n{content}\n--- End resource ---", flush=True)
            output = {"emitted": True, "acknowledged": False, "sha256": entry["loads"][args.resource]["sha256"]}
        elif args.command == "ack": acknowledge(entry, args.resource, args.summary); output = {"acknowledged": True, "type": "agent-attestation"}
        elif args.command == "criterion": output = add_criterion(entry, args.resource, args.quote, args.check, args.replace, args.reason)
        elif args.command == "evidence":
            found = [c for c in entry["criteria"] if c["id"] == args.criterion]
            if len(found) != 1: raise RouterError("Unknown criterion")
            record_evidence(found[0], args.status, args.observation, args.artifact); output = found[0]
        elif args.command == "note":
            if not args.text.strip(): raise RouterError("Note must not be empty")
            run["notes"].append({"at": now(), "text": args.text}); output = {"saved": True}
        elif args.command == "verify":
            output = verify(run)
            run["status"] = "verified" if output["verified"] else "in-progress"
            run["verification"] = {"at": now(), **output}
        if args.command != "verify": run["status"] = "in-progress"
        save_run(state, run)
        emit(output)
        return 1 if args.command == "verify" and not output["verified"] else 0
    except (RouterError, OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"SkillRouter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    # Agent tools consume UTF-8 pipes even on Windows with a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
