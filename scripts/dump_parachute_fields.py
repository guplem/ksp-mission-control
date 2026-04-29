"""Diagnostic script: dump all ModuleParachute fields readable via kRPC.

Run with KSP open and a vessel with parachutes on the pad:
    uv run python scripts/dump_parachute_fields.py

Prints every field name and value from the ModuleParachute module,
so we can find safe-deployment thresholds not exposed by the kRPC
Parachute wrapper.
"""

import krpc


def main() -> None:
    conn = krpc.connect(name="Parachute Field Dump")
    vessel = conn.space_center.active_vessel

    # Check for RealChutes mod
    print("Checking for RealChutes module on any part...")
    for part in vessel.parts.all:
        for module in part.modules:
            if "realchute" in module.name.lower():
                print(f"  Found module '{module.name}' on part '{part.title}'")
                for field_name in module.fields:
                    try:
                        value = module.get_field(field_name)
                        print(f"    {field_name} = {value}")
                    except Exception as exc:
                        print(f"    {field_name} = <error: {exc}>")
    print()

    parachutes = vessel.parts.parachutes
    if not parachutes:
        print("No parachutes found on the active vessel.")
        return

    for i, chute in enumerate(parachutes):
        part = chute.part
        print(f"\n{'=' * 60}")
        print(f"Parachute #{i}: {part.title} (stage {part.decouple_stage})")
        try:
            print(f"kRPC state: {chute.state}")
        except Exception as exc:
            print(f"kRPC state: <error: {exc}>")
        try:
            print(f"deploy_altitude: {chute.deploy_altitude}")
        except Exception as exc:
            print(f"deploy_altitude: <error: {exc}>")
        try:
            print(f"deploy_min_pressure: {chute.deploy_min_pressure}")
        except Exception as exc:
            print(f"deploy_min_pressure: <error: {exc}>")

        # Dump ALL modules on this part
        for module in part.modules:
            print(f"\n--- {module.name} fields ---")
            for field_name in module.fields:
                try:
                    value = module.get_field(field_name)
                    print(f"  {field_name} = {value}")
                except Exception as exc:
                    print(f"  {field_name} = <error: {exc}>")

            if module.events:
                print(f"  [events]: {', '.join(module.events)}")
            if module.actions:
                print(f"  [actions]: {', '.join(module.actions)}")

    conn.close()
    print(f"\n{'=' * 60}")
    print("Done. Check the field list above for safe deployment thresholds.")


if __name__ == "__main__":
    main()
