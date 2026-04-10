# Implement Issue

Implement a GitHub issue end-to-end.

## Arguments

$ARGUMENTS - The issue number or URL to implement

## Process

1. **Read the issue**: `gh issue view $ARGUMENTS`
2. **Understand scope**: Identify which files, models, widgets, or screens are affected.
3. **Branch**: Create a feature branch from main: `git checkout -b feat/ISSUE_NUMBER-short-description`
4. **Plan**: Break the issue into TDD steps (test first, then implementation).
5. **Implement**: For each step:
   a. Write a failing test
   b. Write minimum code to pass
   c. Refactor if needed
   d. Run `uv run pytest` to verify
6. **Review**: Run full test suite, lint (`uv run ruff check src/ tests/`), type check (`uv run mypy`).
7. **PR**: Create a pull request.

## Research Trigger

If the issue is complex or touches unfamiliar areas, ask whether to run `/research-agents` first.

## Agent Delegation

- Run `pattern-scout` before implementing new widgets or models
- Run `adr-checker` if the change touches architecture
- Run `test-runner` after each implementation step
- Run `docs-checker` after all code changes are done

## PR Command

```bash
gh label create waiting-for-human-check --color FBCA04 --force 2>/dev/null
gh pr create --title "TITLE" --body "BODY" --label "waiting-for-human-check" --assignee @me
```

Always include `Closes #ISSUE_NUMBER` in the PR body.
