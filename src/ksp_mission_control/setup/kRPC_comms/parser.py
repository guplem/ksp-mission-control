"""Parse kRPC server connection settings from a KSP installation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

KRPC_SETTINGS_RELATIVE_PATH = Path("GameData/kRPC/PluginData/settings.cfg")


class KrpcSettingsParseError(Exception):
    """Raised when kRPC settings.cfg cannot be read or parsed."""


@dataclass(frozen=True)
class KrpcServerSettings:
    """Connection settings extracted from kRPC settings.cfg."""

    address: str
    rpc_port: int
    stream_port: int


def parse_krpc_settings(ksp_path: Path) -> KrpcServerSettings:
    """Read the first server entry from kRPC settings.cfg at *ksp_path*.

    Parses the KSP ConfigNode format to extract the server address,
    RPC port, and stream port from the ``servers`` block.

    Raises:
        KrpcSettingsParseError: If the file is missing, has no server
            entries, or is missing required connection fields.
    """
    cfg_path = ksp_path / KRPC_SETTINGS_RELATIVE_PATH
    if not cfg_path.is_file():
        raise KrpcSettingsParseError(f"settings.cfg not found at {cfg_path}")

    text = cfg_path.read_text(encoding="utf-8", errors="replace")
    return _parse_first_server(text)


def _parse_first_server(text: str) -> KrpcServerSettings:
    """Extract connection settings from the first server in *text*.

    The kRPC settings.cfg uses a nested ConfigNode structure::

        servers {
            Item {
                settings {
                    Item { key = address   value = 127.0.0.1 }
                    Item { key = rpc_port  value = 50000 }
                    Item { key = stream_port value = 50001 }
                }
            }
        }
    """
    key_value_pattern = re.compile(r"key\s*=\s*(\S+)")
    value_pattern = re.compile(r"value\s*=\s*(\S+)")

    # Find the first "servers" block, then its first "Item > settings" block
    servers_match = re.search(r"servers\s*\{", text)
    if servers_match is None:
        raise KrpcSettingsParseError("No 'servers' block found in settings.cfg")

    # Walk through key/value pairs inside the servers block
    settings_data: dict[str, str] = {}
    servers_text = text[servers_match.end() :]

    # Find all Item blocks within the settings sub-block of the first server Item
    settings_match = re.search(r"settings\s*\{", servers_text)
    if settings_match is None:
        raise KrpcSettingsParseError("No 'settings' block found in server entry")

    settings_text = servers_text[settings_match.end() :]

    # Extract key/value pairs until we hit the closing brace of the settings block
    depth = 1
    pos = 0
    current_key: str | None = None
    for line in settings_text.splitlines():
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break

        key_match = key_value_pattern.search(line)
        if key_match:
            current_key = key_match.group(1)

        value_match = value_pattern.search(line)
        if value_match and current_key is not None:
            settings_data[current_key] = value_match.group(1)
            current_key = None

    required_keys = ("address", "rpc_port", "stream_port")
    missing = [k for k in required_keys if k not in settings_data]
    if missing:
        raise KrpcSettingsParseError(
            f"Missing required server settings: {', '.join(missing)}"
        )

    try:
        return KrpcServerSettings(
            address=settings_data["address"],
            rpc_port=int(settings_data["rpc_port"]),
            stream_port=int(settings_data["stream_port"]),
        )
    except ValueError as exc:
        raise KrpcSettingsParseError(f"Invalid port value: {exc}") from exc
