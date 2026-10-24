# Validation record

Validation performed on 24 October 2026, before the initial release.

## Automated checks

The local Windows/Python 3.12 run executed 28 tests: 27 passed and one symlink test was skipped because the host did not permit creating symlinks. Skill Creator's `quick_validate.py` also accepted the skill. Python compilation and Git whitespace checks passed.

The tests exercise record freshness, exact-source criteria, failed and blocked evidence, duplicate names, invocation policy, path containment, persisted runs, UTF-8 output under a legacy terminal encoding, and installation that preserves user-owned instructions. The encoding check was added after a real Windows terminal load garbled non-ASCII characters. GitHub Actions defines the same suite for Windows/Linux on Python 3.10/3.12; a defined workflow alone is not evidence of a passing hosted run.

## Independent behavioral pass

A separate agent received the skill and realistic requests without the intended routing answers or access to the unit tests. It observed:

| Scenario | Observed behavior |
| --- | --- |
| Interactive 3D neural-network explanation without a reference image | Chose an installed interactive-visualization capability; excluded image-to-3D because its input prerequisite was missing. |
| Find support for an unspecified format, with installation prohibited | Loaded find-skills and the bridge; retained the no-install boundary and did not claim an external search in the network-disabled evaluation. |
| One README typo | Chose a direct edit and diff check, with no catalog scan or elaborate workflow. |

The agent also completed a CLI run with a synthetic skill, a supporting reference, and a small UTF-8 artifact. Three exact-source criteria remained unverified until a real artifact checker passed and evidence was supplied. A subsequent verify returned true; recall and coverage reported the persisted result. This exercised the published interface independently of the tests.

No blocking defect was observed. Delivery mode for an unspecified “interactive explanation” remained a legitimate judgment call: inline output was reasonable, while an explicit website or file request would change the route.

## What this establishes

These results support the routing protocol's usability and its documented mechanical checks. They do not measure general intelligence gains, prove truthful agent attestations, guarantee correct routing for all prompts, or show that every installed skill was understood. Broader quality claims would require task-specific comparisons on real outputs.
