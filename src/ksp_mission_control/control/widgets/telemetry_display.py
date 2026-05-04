"""TelemetryDisplayWidget - displays live vessel telemetry."""

from __future__ import annotations

import math

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from ksp_mission_control.control.actions.base import ScienceExperiment, State
from ksp_mission_control.control.formatting import format_met, resolve_theme_colors
from ksp_mission_control.control.widgets.telemetry_alerts import (
    ALERT_COLOR_VARIABLE,
    AlertLevel,
    evaluate_comms_connected,
    evaluate_comms_signal_strength,
    evaluate_dynamic_pressure,
    evaluate_electric_charge,
    evaluate_engine_flameouts,
    evaluate_fuel_fraction,
    evaluate_g_force,
    evaluate_liquid_fuel,
    evaluate_mono_propellant,
    evaluate_oxidizer,
    evaluate_periapsis,
    evaluate_time_to_impact,
    evaluate_twr,
)


class ScienceCardWidget(Static, can_focus=False):
    """Interactive card for a single science experiment. Clickable with tooltip."""

    class Selected(Message):
        """Posted when the user clicks a science card."""

        def __init__(self, experiment_index: int) -> None:
            super().__init__()
            self.experiment_index = experiment_index

    DEFAULT_CSS = """
    ScienceCardWidget {
        width: 1fr;
        height: 7;
        padding: 0 1;
        border: round $warning;
    }

    ScienceCardWidget.has-data {
        border: round $success;
    }

    ScienceCardWidget.inoperable {
        border: round $error;
        opacity: 60%;
    }

    ScienceCardWidget.unavailable {
        border: round $surface-lighten-2;
    }

    ScienceCardWidget:hover {
        background: $surface-lighten-1;
    }
    """

    def __init__(self, experiment: ScienceExperiment) -> None:
        super().__init__(_science_card_content(experiment))
        self._experiment = experiment
        classes = _science_card_classes(experiment)
        if classes:
            self.add_class(*classes.split())
        self.tooltip = _science_tooltip(experiment)

    def update_experiment(self, experiment: ScienceExperiment) -> None:
        """Update the card with fresh experiment data."""
        old_classes = _science_card_classes(self._experiment)
        new_classes = _science_card_classes(experiment)
        if old_classes:
            self.remove_class(*old_classes.split())
        if new_classes:
            self.add_class(*new_classes.split())
        self._experiment = experiment
        self.update(_science_card_content(experiment))
        self.tooltip = _science_tooltip(experiment)

    def on_click(self, event: Click) -> None:
        self.post_message(self.Selected(self._experiment.index))


class TelemetryDisplayWidget(Static):
    """Displays formatted vessel telemetry in three columns: Flight & Environment, Orbit & Vessel, Controls & Resources."""

    class ScienceExperimentClicked(Message):
        """Posted when the user clicks a science experiment card."""

        def __init__(self, experiment: ScienceExperiment) -> None:
            super().__init__()
            self.experiment = experiment

    DEFAULT_CSS = """
    #telemetry-header {
        height: auto;
        padding: 0 0 1 0;
    }

    #telemetry-title {
        width: 1fr;
    }

    #telemetry-ut {
        width: auto;
    }

    #telemetry-columns {
        height: auto;
    }

    .telemetry-column {
        width: 1fr;
        padding: 0 1;
    }

    #telemetry-science-header {
        height: auto;
        padding: 1 1 0 1;
    }

    #telemetry-science-grid {
        height: auto;
        layout: grid;
        grid-size: 3;
        grid-gutter: 1;
        padding: 0 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:  # noqa: A002
        super().__init__(id=id)
        self._science_experiments: tuple[ScienceExperiment, ...] = ()
        self._alert_colors: dict[AlertLevel, str] | None = None
        self._frozen: bool = False

    def _resolve_alert_colors(self) -> dict[AlertLevel, str]:
        if self._alert_colors is None:
            self._alert_colors = resolve_theme_colors(self.app, ALERT_COLOR_VARIABLE)
        return self._alert_colors

    def compose(self) -> ComposeResult:
        with Horizontal(id="telemetry-header"):
            yield Static("[b]Telemetry[/b]", id="telemetry-title")
            yield Static("", id="telemetry-ut")
        with Horizontal(id="telemetry-columns"):
            yield Static("Connecting...", id="telemetry-flight", classes="telemetry-column")
            yield Static("", id="telemetry-orbit", classes="telemetry-column")
            yield Static("", id="telemetry-resources", classes="telemetry-column")
        yield Static("", id="telemetry-science-header")
        yield Container(id="telemetry-science-grid")

    def update_vessel_state(self, state: State) -> None:
        """Format and display the current vessel state across three columns.

        Ignored while the widget is frozen (showing historical data).
        """
        if self._frozen:
            return
        self._render_state(state)
        self.query_one("#telemetry-title", Static).update("[b]Telemetry[/b]")

    def show_historical_state(self, state: State, met: float) -> None:
        """Display a historical state snapshot and freeze live updates."""
        self._frozen = True
        self._render_state(state)
        self.query_one("#telemetry-title", Static).update(f"[b]Telemetry[/b]  [dim italic]{format_met(met)} (historical)[/dim italic]")

    def resume_live(self) -> None:
        """Unfreeze and resume accepting live state updates."""
        self._frozen = False
        self.query_one("#telemetry-title", Static).update("[b]Telemetry[/b]")

    def _render_state(self, state: State) -> None:
        """Render a State snapshot into the three telemetry columns."""
        colors = self._resolve_alert_colors()
        self.query_one("#telemetry-ut", Static).update(f"UT: {_format_time(state.universal_time)} ")
        self.query_one("#telemetry-flight", Static).update(_format_flight(state, colors))
        self.query_one("#telemetry-orbit", Static).update(_format_orbit(state, colors))
        self.query_one("#telemetry-resources", Static).update(_format_resources(state, colors))
        self._update_science(state)

    def _update_science(self, state: State) -> None:
        """Update the science experiments section below the telemetry grid."""
        experiments = state.science_experiments
        self._science_experiments = experiments
        science_header = self.query_one("#telemetry-science-header", Static)
        grid = self.query_one("#telemetry-science-grid", Container)

        if not experiments:
            science_header.update("")
            grid.remove_children()
            return

        science_header.update("[b]Science Experiments[/b]")
        existing_cards = list(grid.query(ScienceCardWidget))

        # Reuse existing cards where possible, add/remove as needed
        for idx, exp in enumerate(experiments):
            if idx < len(existing_cards):
                existing_cards[idx].update_experiment(exp)
            else:
                grid.mount(ScienceCardWidget(exp))

        # Remove excess cards
        for card in existing_cards[len(experiments) :]:
            card.remove()

    def on_science_card_widget_selected(self, event: ScienceCardWidget.Selected) -> None:
        """Re-post the click as a ScienceExperimentClicked with the full experiment object."""
        for exp in self._science_experiments:
            if exp.index == event.experiment_index:
                self.post_message(self.ScienceExperimentClicked(exp))
                break


def _format_altitude(meters: float) -> str:
    """Format altitude/distance with appropriate unit (m or km)."""
    if abs(meters) >= 100_000:
        return f"{meters / 1000:.1f} km"
    return f"{meters:.0f} m"


def _format_time(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    if seconds == 0.0 or seconds == float("inf"):
        return "N/A"
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    if seconds < 60:
        return f"{sign}{seconds:.0f}s"
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    if minutes < 60:
        return f"{sign}{minutes}m {secs:02d}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{sign}{hours}h {mins:02d}m {secs:02d}s"


def _magnitude(vector: tuple[float, float, float]) -> float:
    """Compute the magnitude of a 3D vector."""
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def _format_force(newtons: float) -> str:
    """Format force in N or kN."""
    if newtons >= 1000:
        return f"{newtons / 1000:.1f} kN"
    return f"{newtons:.1f} N"


def _format_mass(kg: float) -> str:
    """Format mass in kg or t."""
    if kg >= 1000:
        return f"{kg / 1000:.2f} t"
    return f"{kg:.1f} kg"


def _color(text: str, level: AlertLevel, colors: dict[AlertLevel, str]) -> str:
    """Wrap text in Rich color tags if the alert level is above NORMAL."""
    if level == AlertLevel.NORMAL:
        return text
    hex_color = colors[level]
    return f"[{hex_color}]{text}[/{hex_color}]"


def _format_flight(state: State, colors: dict[AlertLevel, str]) -> str:
    return "\n".join(
        [
            "[b]Overview[/b]",
            f"Vessel:          {state.name}",
            f"Situation:       {state.situation.display_name}",
            f"MET:             {_format_time(state.met)}",
            f"G-force:         {_color(f'{state.g_force:.2f} g', evaluate_g_force(state), colors)}",
            "",
            "[b]Altitude[/b]",
            f"Surface:         {_format_altitude(state.altitude_surface)}",
            f"Sea level:       {_format_altitude(state.altitude_sea)}",
            f"Time to impact:  {_color(_format_time(state.altitude_time_to_impact), evaluate_time_to_impact(state), colors)}",
            "",
            "[b]Speed[/b]",
            f"Vertical:        {state.speed_vertical:+.1f} m/s",
            f"Horizontal:      {state.speed_horizontal:.1f} m/s",
            f"Surface:         {state.speed_surface:.1f} m/s",
            f"Orbital:         {state.speed_orbital:.1f} m/s",
            "",
            "[b]Position[/b]",
            f"Body:            {state.body_name}",
            f"Latitude:        {state.position_latitude:.4f} deg",
            f"Longitude:       {state.position_longitude:.4f} deg",
            "",
            "[b]Atmosphere[/b]",
            f"In atmosphere:   {'Yes' if state.in_atmosphere else 'No'}",
            f"Dynamic press.:  {_color(f'{state.pressure_dynamic / 1000:.2f} kPa', evaluate_dynamic_pressure(state), colors)}",
            f"Static press.:   {state.pressure_static / 1000:.2f} kPa",
            f"Mach:            {state.aero_mach:.2f}",
            f"AoA:             {state.aero_angle_of_attack:.1f} deg",
            f"Terminal vel.:   {state.aero_terminal_velocity:.1f} m/s",
            f"Drag:            {_format_force(_magnitude(state.aero_drag))}",
            f"Lift:            {_format_force(_magnitude(state.aero_lift))}",
        ]
    )


def _on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def _format_orbit(state: State, colors: dict[AlertLevel, str]) -> str:
    periapsis_level = evaluate_periapsis(state)
    return "\n".join(
        [
            "[b]Orbit[/b]",
            f"Apoapsis:        {_format_altitude(state.orbit_apoapsis)}",
            f"T to apoapsis:   {_format_time(state.orbit_apoapsis_time_to)}",
            f"T from apoapsis: {_format_time(state.orbit_apoapsis_time_from)}",
            f"Periapsis:       {_color(_format_altitude(state.orbit_periapsis), periapsis_level, colors)}",
            f"T to periapsis:  {_format_time(state.orbit_periapsis_time_to)}",
            f"T from periapsis:{_format_time(state.orbit_periapsis_time_from)}",
            f"Inclination:     {state.orbit_inclination:.2f} deg",
            f"Eccentricity:    {state.orbit_eccentricity:.4f}",
            f"Period:          {_format_time(state.orbit_period)}",
            "",
            "[b]Orientation[/b]",
            f"Pitch:           {state.orientation_pitch:.1f} deg",
            f"Heading:         {state.orientation_heading:.1f} deg",
            f"Roll:            {state.orientation_roll:.1f} deg",
            "",
            "[b]Propulsion[/b]",
            f"TWR:             {_color(f'{state.twr:.2f}', evaluate_twr(state), colors)} / {state.max_twr:.2f}",
            f"Delta-v:         {state.delta_v:.0f} m/s",
            f"Thrust:          {_format_force(state.thrust)} / {_format_force(state.thrust_peak)}",
            f"Mass:            {_format_mass(state.mass)}",
            f"Isp:             {state.engine_impulse_specific:.1f} s",
            f"Fuel fraction:   {_color(f'{state.fuel_fraction * 100:.1f}%', evaluate_fuel_fraction(state), colors)}",
            f"Flameouts:       {_color(str(state.engine_flameout_count), evaluate_engine_flameouts(state), colors)}",
            "",
            "[b]Comms[/b]",
            f"Connected:       {_color(_on_off(state.comms_connected), evaluate_comms_connected(state), colors)}",
            f"Signal:          {_color(f'{state.comms_signal_strength * 100:.0f}%', evaluate_comms_signal_strength(state), colors)}",
        ]
    )


def _format_resource(amount: float, fraction: float) -> str:
    """Format a resource as 'amount units (percent%)'."""
    return f"{amount:.1f} ({fraction * 100:.0f}%)"


def _color_resource(label: str, amount: float, fraction: float, level: AlertLevel, colors: dict[AlertLevel, str]) -> str:
    """Format a resource line with alert coloring."""
    return f"{label} {_color(_format_resource(amount, fraction), level, colors)}"


def _format_resources(state: State, colors: dict[AlertLevel, str]) -> str:
    return "\n".join(
        [
            "[b]Resources[/b]",
            _color_resource(
                "Electric charge:",
                state.resource_electric_charge,
                state.resource_electric_charge_fraction,
                evaluate_electric_charge(state),
                colors,
            ),
            _color_resource(
                "Liquid fuel:    ",
                state.resource_liquid_fuel,
                state.resource_liquid_fuel_fraction,
                evaluate_liquid_fuel(state),
                colors,
            ),
            _color_resource(
                "Oxidizer:       ",
                state.resource_oxidizer,
                state.resource_oxidizer_fraction,
                evaluate_oxidizer(state),
                colors,
            ),
            _color_resource(
                "Mono propellant:",
                state.resource_mono_propellant,
                state.resource_mono_propellant_fraction,
                evaluate_mono_propellant(state),
                colors,
            ),
            "",
            "[b]Controls[/b]",
            f"Throttle:        {state.control_throttle * 100:.0f}%",
            f"Stage:           {state.stage_current} (remaining)",
            f"SAS:             {_on_off(state.control_sas)}",
            f"SAS mode:        {state.control_sas_mode.display_name if state.control_sas_mode is not None else '-'}",
            f"RCS:             {_on_off(state.control_rcs)}",
            "",
            "[b]Toggles[/b]",
            f"Gear:            {_on_off(state.control_gear)}",
            f"Legs:            {_on_off(state.control_legs)}",
            f"Brakes:          {_on_off(state.control_brakes)}",
            f"Lights:          {_on_off(state.control_lights)}",
            f"Abort:           {_on_off(state.control_abort)}",
            "",
            "[b]Inputs[/b]",
            f"Pitch:           {state.control_input_pitch:+.2f}",
            f"Yaw:             {state.control_input_yaw:+.2f}",
            f"Roll:            {state.control_input_roll:+.2f}",
            "",
            "[b]Deployables[/b]",
            f"Parachutes:      {_on_off(state.control_deployable_parachutes)}",
            f"Solar panels:    {_on_off(state.control_deployable_solar_panels)}",
            f"Antennas:        {_on_off(state.control_deployable_antennas)}",
            f"Radiators:       {_on_off(state.control_deployable_radiators)}",
            f"Cargo bays:      {_on_off(state.control_deployable_cargo_bays)}",
            f"Intakes:         {_on_off(state.control_deployable_intakes)}",
        ]
    )


def _science_card_content(exp: ScienceExperiment) -> str:
    """Format the Rich markup content for a science card."""
    icon = _science_status_icon(exp)
    subtitle = exp.name_tag if exp.name_tag else exp.part_title
    return f"{icon} [b]{exp.title}[/b]\n[dim]{subtitle}[/dim]\nData value: {exp.science_value:.1f}/{exp.science_cap:.1f}"


def _science_status_icon(exp: ScienceExperiment) -> str:
    """Return a status indicator character for a science experiment."""
    if exp.inoperable:
        return "X"
    if exp.has_data:
        return "v"
    if exp.available:
        return "o"
    return "-"


def _science_status_label(exp: ScienceExperiment) -> str:
    """Return a human-readable status label for a science experiment."""
    if exp.inoperable:
        return "Inoperable"
    if exp.has_data:
        return "Has Data"
    if exp.available:
        return "Available"
    return "Unavailable"


def _science_card_classes(exp: ScienceExperiment) -> str:
    """Return CSS classes for a science card based on experiment state."""
    if exp.inoperable:
        return "inoperable"
    if exp.has_data:
        return "has-data"
    if not exp.available:
        return "unavailable"
    return ""


def _science_tooltip(exp: ScienceExperiment) -> str:
    """Build a tooltip string explaining the experiment's fields."""
    rerunnable = "Yes" if exp.rerunnable else "No"
    tag_line = f"Name tag: {exp.name_tag}\n" if exp.name_tag else ""
    return (
        f"Index: {exp.index}\n"
        f"Title: {exp.title} (display name)\n"
        f"Name: {exp.name} (internal experiment ID)\n"
        f"Part: {exp.part_title} (containing part)\n"
        f"{tag_line}"
        f"\n"
        f"Status: {_science_status_label(exp)}\n"
        f"Rerunnable: {rerunnable}\n"
        f"Data value: {exp.science_value:.1f}/{exp.science_cap:.1f} (stored/max)\n"
        f"\n"
        f"Click to send a science command"
    )
