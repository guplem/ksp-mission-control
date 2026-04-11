"""Sequential check executor with short-circuit on failure."""

from __future__ import annotations

from collections.abc import Callable

from ksp_mission_control.setup.checks import CheckResult, SetupCheck


class CheckRunner:
    """Executes setup checks sequentially, short-circuiting on first failure.

    Communicates progress via a typed callback. Has no Textual dependency;
    the caller is responsible for threading and bridging updates to the UI.
    """

    def __init__(
        self,
        checks: list[SetupCheck],
        on_update: Callable[[str, str, CheckResult | None, bool], None],
    ) -> None:
        self._checks = checks
        self._on_update = on_update
        self._results: dict[str, CheckResult] = {}

    @property
    def all_passed(self) -> bool:
        """Return True when every check has been run and passed."""
        return len(self._results) == len(self._checks) and all(
            r.passed for r in self._results.values()
        )

    def run_all(self) -> None:
        """Reset results and execute checks sequentially.

        Calls ``on_update(check_id, label, None, True)`` before each check
        and ``on_update(check_id, label, result, False)`` after. Stops on
        first failure.

        This method is synchronous and blocking. The caller should run it
        in a worker thread to keep the UI responsive.
        """
        self._results.clear()

        for check in self._checks:
            self._on_update(check.check_id, check.label, None, True)

            result = check.run()
            self._results[check.check_id] = result

            self._on_update(check.check_id, check.label, result, False)

            if not result.passed:
                break
