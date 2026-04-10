# ADR 0005: Test-Driven Development Workflow

## Context

The project owner requires TDD (red-green-refactor) for all functionality. This is a conscious choice to ensure testability from the start, especially important for a project with complex external dependencies (kRPC, Textual).

## Decision

Follow strict TDD:

1. **Red**: Write a failing test for the desired behavior
2. **Green**: Write minimum code to pass the test
3. **Refactor**: Clean up while keeping tests green

Test framework: **pytest** with `pytest-asyncio` for async tests and Textual's `pilot` for widget testing.

Test structure mirrors source: `tests/test_<module>.py`.

## Consequences

- **Positive**: High test coverage from day one
- **Positive**: Forces clean interfaces (if it's hard to test, the design needs work)
- **Positive**: Safe refactoring as the project grows
- **Negative**: Slower initial development velocity
- **Negative**: Textual widget testing has some quirks (pilot API, async mounting)
