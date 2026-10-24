# Repository guidance

Keep SkillRouter local, honest about its verification limits, and compatible
with Python 3.10+. Do not add network calls, telemetry, or automatic execution
of commands from skill text. Keep personal catalogs, task records and backups
out of Git.

Run `python -m unittest discover -s tests -v` after behavior changes. Validate
SKILL.md with the available skill-creator validator. Keep CLI examples aligned
with the actual interface and test observable failure modes.

Preserve existing user instructions during installation. Do not copy third-party
skills into this repository. Keep normal implicit invocation enabled.
