# Bridge to find-skills

Use the installed `find-skills` skill when local capabilities genuinely leave a gap, or when the user explicitly asks to find/install skills. Resolve its path from the current session catalog or the router index. Read it before searching. If unavailable, say so and use available discovery tools or provide a precise search query; do not pretend it ran.

Pass a small gap description: desired outcome, input/output formats, chosen stack, unavailable capability, and constraints. Do not include private task text, secrets, file contents, or local inventory in a public search query.

The installed find-skills workflow may use the skills.sh leaderboard and `npx skills find`. Treat popularity as provenance context, not proof of correctness. Inspect the candidate's actual SKILL.md and executable helpers, dependencies, license, maintenance signals, and scope before recommending it. Do not manufacture install counts or star totals. A small, relevant, reviewed skill can outperform a popular mismatch.

Respect existing authorization. Finding a missing capability does not authorize installing arbitrary code or changing global settings. When installation was requested, perform the authorized install through the available installer and reindex its root. Otherwise offer a concrete candidate or continue with existing capabilities.

Return a handoff with: inspected source, capability supplied, compatibility decision, installation status, and any remaining gap. Resume the existing routing decision. Do not send the task back to find-skills merely because it referred to SkillRouter; one round trip per gap, another only after materially new evidence.

The repository installer can append a bounded bridge to an existing find-skills SKILL.md. It preserves the original file, keeps a backup, and does not redistribute that third-party skill. The bridge tells find-skills to check local coverage and then return to this workflow for application and evidence.
