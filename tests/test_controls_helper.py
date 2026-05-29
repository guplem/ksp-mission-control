"""Tests for the release_controls helper.

The helper resets the three "active control" fields on a VesselCommands
buffer: throttle, autopilot, and SAS. Used by stop() bodies that need to
hand the vessel back without leaving any of those engaged.
"""

from __future__ import annotations

from ksp_mission_control.control.actions.base import (
    SASMode,
    VesselCommands,
)
from ksp_mission_control.control.actions.helpers.controls import release_controls


class TestReleaseControls:
    def test_sets_throttle_autopilot_sas(self) -> None:
        commands = VesselCommands()
        release_controls(commands)
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.sas is False

    def test_overwrites_previously_set_fields(self) -> None:
        # Even if a tick() body wrote engaged values into the buffer, the
        # helper's job is to wipe them clean for stop().
        commands = VesselCommands(throttle=0.8, autopilot=True, sas=True, sas_mode=SASMode.PROGRADE)
        release_controls(commands)
        assert commands.throttle == 0.0
        assert commands.autopilot is False
        assert commands.sas is False
        # sas_mode is not the helper's responsibility; leave it alone so
        # actions can record what mode they last asked for.
        assert commands.sas_mode == SASMode.PROGRADE

    def test_does_not_touch_unrelated_fields(self) -> None:
        # Helper has one job: the three active-control fields. Other
        # cleanup (RCS, brakes, node removal) belongs to the action.
        commands = VesselCommands(rcs=True, brakes=True, remove_node_at_ut=100.0)
        release_controls(commands)
        assert commands.rcs is True
        assert commands.brakes is True
        assert commands.remove_node_at_ut == 100.0
