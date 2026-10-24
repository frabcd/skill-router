# Local CLI

Requires Python 3.10+ and PyYAML 6.x. The installer checks both. Use the available Python interpreter; do not assume `python` resolves to a working runtime on Windows. All commands are local, with UTF-8 JSON output except `load`, which emits the full requested UTF-8 text followed by a receipt. No skill scripts or commands in skill text are executed.

In the examples, `ROUTER` means the full path to this skill's `scripts/router.py`. Replace `RUN` and `CRITERION` with IDs returned by commands. `--state` is a global option and comes before the command. Omit it for the user-wide default or choose an approved, gitignored project path. Use one writer per run; separate runs have distinct files.

```sh
python ROUTER --state .skill-router index --root /path/to/enabled/skills
python ROUTER --state .skill-router list
python ROUTER --state .skill-router rank "render mathematical animations with 3b1b" --require manimgl-best-practices
python ROUTER --state .skill-router begin --task "Check one animation" --select "manimgl-best-practices::Create and inspect the requested ManimGL scene"
python ROUTER --state .skill-router load RUN manimgl-best-practices
python ROUTER --state .skill-router ack RUN manimgl-best-practices --summary "Use manimlib and ManimGL creation animations for this scene."
```

Repeat `--root` for personal skills, repository-local skills, system skills, and known-active plugin skill directories. Hidden directories such as `.system` are included; symlink directories are not traversed. Pass a linked skill's real directory as an explicit root if needed. Subsequent `index` without roots refreshes the saved roots. Index errors are returned and stored, not silently treated as successfully read skills. `list` contains full descriptions and paths; `rank` returns candidates with matched terms. It does not understand negation or all semantic synonyms. `--require` overrides implicit-only restrictions for an explicitly requested skill; `--exclude` removes a candidate. These are routing choices, not execution permissions.

`begin` preserves the supplied skill order. Each `--select` has `name-or-id::task-specific purpose`. Names with duplicates must use the exact catalog ID. Source changes require reindexing before starting. No external plugin is activated by listing its directory.

For supporting files, use the same `--resource` in `load`, `ack` and `criterion`:

```sh
python ROUTER --state .skill-router load RUN manimgl-best-practices --resource rules/animations.md
python ROUTER --state .skill-router ack RUN manimgl-best-practices --resource rules/animations.md --summary "Use ShowCreation for the requested shape drawing."
python ROUTER --state .skill-router criterion RUN manimgl-best-practices --resource rules/animations.md --quote "EXACT EXCERPT FROM THE FILE YOU READ" --check "Describe an observable requirement for this artifact."
python ROUTER --state .skill-router evidence RUN manimgl-best-practices CRITERION --status pass --observation "Record what was checked, how, and the actual result." --artifact /path/to/real-check-output.txt
python ROUTER --state .skill-router verify RUN
```

Choose actual source text; the placeholder excerpt above is deliberately not a valid criterion. The exact quote is 10-500 characters. Evidence statuses are `pass`, `fail`, and `blocked`. Artifact hashing is optional; the observation is always required. The script never executes the observation as a command. Every selected skill must have its main SKILL.md loaded and acknowledged, and at least one current criterion with passing evidence. An agent must determine whether the criteria cover all applicable requirements.

After a changed source, reload and acknowledge it. Use `criterion --replace CRITERION --reason "Why the contract changed"` with a current quote and check to preserve the old contract and its evidence under `supersedes`. The new criterion starts pending. Replacing a failed criterion just to get a pass violates the workflow.

```sh
python ROUTER --state .skill-router note RUN "Short, non-sensitive lesson backed by the outcome."
python ROUTER --state .skill-router recall --skill manimgl-best-practices --limit 3
python ROUTER --state .skill-router coverage
```

Notes after completion invalidate the saved completion state; run `verify` again. `recall` returns validation against current files, including stale evidence. `coverage` never counts stale historical passes as currently verified. Main-file metadata cannot tell whether a plugin is actually enabled; compare the live session catalog.

Exit codes: 0 for success, 1 for an unmet verification or an empty index, 2 for invalid arguments/state/resources. The index may contain valid entries and errors together; inspect its `errors` before claiming complete coverage.
