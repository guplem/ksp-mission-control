# Create Issue

Interactive issue creation for ksp-mission-control.

## Process

1. **Clarify**: Ask what the issue is about. Gather enough detail for a clear title and description.
2. **Investigate**: Search the codebase for relevant files, existing patterns, and related code.
3. **Duplicate check**: Search existing issues with `gh issue list --search "keywords"`.
4. **Draft**: Write a clear title and description with:
   - What should happen vs what happens (bugs) or what should be built (features)
   - Relevant file paths and code references
   - Acceptance criteria
5. **Label**: Auto-detect appropriate labels (bug, enhancement, etc.)
6. **Create**: Submit with the command below.

## Anti-Redundancy Rules

- Never create an issue that duplicates an existing one. If a similar issue exists, comment on it instead.
- Never create issues for trivial changes that can be done directly.

## Research Trigger

If the feature is broad or exploratory, ask whether to run `/research-agents` before creating the issue.

## Create Command

```bash
gh label create waiting-for-human-check --color FBCA04 --force 2>/dev/null
gh issue create --title "TITLE" --body "BODY" --label "waiting-for-human-check,LABELS" --assignee @me
```
