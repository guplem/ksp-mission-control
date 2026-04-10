# Review PR Comments

Review and respond to comments on a pull request.

## Arguments

$ARGUMENTS - The PR number or URL to review

## Process

1. **Read comments**: `gh api repos/OWNER/REPO/pulls/PR_NUMBER/comments`
2. **Read review comments**: `gh api repos/OWNER/REPO/pulls/PR_NUMBER/reviews`
3. **For each comment**, make an evidence-based decision:

### Decision Categories

- **Apply**: The comment is correct. Make the change, cite the specific fix.
- **Reject**: The comment is incorrect or doesn't apply. Explain why with evidence (code references, test results, documentation).
- **Ambiguous**: The comment could go either way. Present both sides and ask the user.

4. **Respond**: Post a reply to each comment on GitHub with your decision and reasoning.

## Reply Command

```bash
gh api repos/OWNER/REPO/pulls/PR_NUMBER/comments/COMMENT_ID/replies -f body="RESPONSE"
```

## Guidelines

- Never dismiss a comment without evidence
- If a comment suggests a test, write the test to verify
- If applying a change, run `uv run pytest` after to verify nothing breaks
