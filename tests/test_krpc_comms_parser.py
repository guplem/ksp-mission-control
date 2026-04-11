"""Tests for the kRPC settings.cfg parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from ksp_mission_control.setup.kRPC_comms.parser import (
    KrpcServerSettings,
    KrpcSettingsParseError,
    parse_krpc_settings,
)


def _write_settings(ksp_path: Path, content: str) -> Path:
    """Write a settings.cfg inside the expected kRPC PluginData directory."""
    cfg_dir = ksp_path / "GameData" / "kRPC" / "PluginData"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "settings.cfg"
    cfg_path.write_text(content)
    return cfg_path


VALID_SETTINGS = """\
KRPCConfiguration
{
    servers
    {
        Item
        {
            id = 0af10251-3d1d-4796-b3e8-9c73947d69c0
            name = Default Server
            protocol = ProtocolBuffersOverTCP
            settings
            {
                Item
                {
                    key = address
                    value = 127.0.0.1
                }
                Item
                {
                    key = rpc_port
                    value = 50000
                }
                Item
                {
                    key = stream_port
                    value = 50001
                }
            }
        }
    }
}
"""


class TestParseKrpcSettings:
    """Tests for parsing kRPC settings.cfg files."""

    def test_parses_valid_settings(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, VALID_SETTINGS)
        result = parse_krpc_settings(tmp_path)
        assert result == KrpcServerSettings(
            address="127.0.0.1", rpc_port=50000, stream_port=50001
        )

    def test_parses_custom_address_and_ports(self, tmp_path: Path) -> None:
        content = VALID_SETTINGS.replace("127.0.0.1", "0.0.0.0")
        content = content.replace("50000", "60000")
        content = content.replace("50001", "60001")
        _write_settings(tmp_path, content)
        result = parse_krpc_settings(tmp_path)
        assert result == KrpcServerSettings(
            address="0.0.0.0", rpc_port=60000, stream_port=60001
        )

    def test_raises_when_file_missing(self, tmp_path: Path) -> None:
        with pytest.raises(KrpcSettingsParseError, match="not found"):
            parse_krpc_settings(tmp_path)

    def test_raises_when_no_servers_block(self, tmp_path: Path) -> None:
        _write_settings(tmp_path, "KRPCConfiguration\n{\n}\n")
        with pytest.raises(KrpcSettingsParseError, match="No 'servers' block"):
            parse_krpc_settings(tmp_path)

    def test_raises_when_no_settings_block(self, tmp_path: Path) -> None:
        content = """\
KRPCConfiguration
{
    servers
    {
        Item
        {
            id = test
            name = Test
        }
    }
}
"""
        _write_settings(tmp_path, content)
        with pytest.raises(KrpcSettingsParseError, match="No 'settings' block"):
            parse_krpc_settings(tmp_path)

    def test_raises_when_missing_keys(self, tmp_path: Path) -> None:
        content = """\
KRPCConfiguration
{
    servers
    {
        Item
        {
            id = test
            settings
            {
                Item
                {
                    key = address
                    value = 127.0.0.1
                }
            }
        }
    }
}
"""
        _write_settings(tmp_path, content)
        with pytest.raises(KrpcSettingsParseError, match="Missing required"):
            parse_krpc_settings(tmp_path)

    def test_raises_on_invalid_port(self, tmp_path: Path) -> None:
        content = VALID_SETTINGS.replace("value = 50000", "value = notanumber")
        _write_settings(tmp_path, content)
        with pytest.raises(KrpcSettingsParseError, match="Invalid port"):
            parse_krpc_settings(tmp_path)
