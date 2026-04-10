# Research Agents

Multi-agent research orchestrator for exploring complex topics.

## Arguments

$ARGUMENTS - The research question or topic

## Process

1. **Decompose**: Break the research question into 2-4 independent sub-questions.
2. **Dispatch**: Launch a research-agent for each sub-question in parallel.
3. **Collect**: Gather all research reports.
4. **Cross-pollinate**: If any agent's findings are relevant to another's question, share them.
5. **Synthesize**: Launch research-synthesizer with all reports to produce a unified recommendation.
6. **Report**: Present the synthesis to the user with clear next steps.

## When to Use

- Evaluating multiple technical approaches
- Investigating unfamiliar kRPC APIs or Textual features
- Understanding complex KSP game mechanics for implementation
- Comparing dependency options

## Example Sub-Questions

For "How should we implement the maneuver planner?":
1. What kRPC APIs are available for maneuver nodes?
2. What Textual widgets work best for numeric input forms?
3. How do other KSP tools handle maneuver planning UX?
4. What orbital mechanics calculations do we need?
