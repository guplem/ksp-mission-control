"""Tests for kRPC mod installer."""

from __future__ import annotations

import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from ksp_mission_control.setup.installer import (
    KRPC_GITHUB_REPO,
    KrpcInstallError,
    extract_krpc_zip,
    get_latest_krpc_download_url,
    install_krpc,
)


class TestKrpcGithubRepo:
    def test_repo_value(self) -> None:
        assert KRPC_GITHUB_REPO == "krpc/krpc"


class TestExtractKrpcZip:
    """Tests for extracting kRPC from a zip archive into GameData/."""

    def _make_krpc_zip(self, zip_path: Path) -> None:
        """Create a fake kRPC release zip with the expected structure."""
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("GameData/kRPC/kRPC.dll", b"fake-dll-content")
            zf.writestr("GameData/kRPC/KRPC.SpaceCenter.dll", b"fake")
            zf.writestr("GameData/kRPC/plugin.cfg", b"[config]")

    def test_extracts_gamedata_contents(self, tmp_path: Path) -> None:
        """Should extract GameData/* into the KSP GameData directory."""
        ksp_dir = tmp_path / "ksp"
        (ksp_dir / "GameData").mkdir(parents=True)

        zip_path = tmp_path / "krpc.zip"
        self._make_krpc_zip(zip_path)

        extract_krpc_zip(zip_path, ksp_dir)

        assert (ksp_dir / "GameData" / "kRPC" / "kRPC.dll").is_file()
        assert (ksp_dir / "GameData" / "kRPC" / "KRPC.SpaceCenter.dll").is_file()
        assert (ksp_dir / "GameData" / "kRPC" / "plugin.cfg").is_file()

    def test_ignores_non_gamedata_entries(self, tmp_path: Path) -> None:
        """Files outside GameData/ in the zip should not be extracted."""
        ksp_dir = tmp_path / "ksp"
        (ksp_dir / "GameData").mkdir(parents=True)

        zip_path = tmp_path / "krpc.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("GameData/kRPC/kRPC.dll", b"dll")
            zf.writestr("README.md", b"readme")
            zf.writestr("client/krpc-python.zip", b"python-client")

        extract_krpc_zip(zip_path, ksp_dir)

        assert (ksp_dir / "GameData" / "kRPC" / "kRPC.dll").is_file()
        assert not (ksp_dir / "README.md").exists()
        assert not (ksp_dir / "client").exists()

    def test_creates_gamedata_if_missing(self, tmp_path: Path) -> None:
        """Should create GameData/ if it doesn't exist yet."""
        ksp_dir = tmp_path / "ksp"
        ksp_dir.mkdir()
        # No GameData/ directory

        zip_path = tmp_path / "krpc.zip"
        self._make_krpc_zip(zip_path)

        extract_krpc_zip(zip_path, ksp_dir)

        assert (ksp_dir / "GameData" / "kRPC" / "kRPC.dll").is_file()

    def test_raises_on_invalid_zip(self, tmp_path: Path) -> None:
        ksp_dir = tmp_path / "ksp"
        ksp_dir.mkdir()

        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"not a zip file")

        with pytest.raises(KrpcInstallError, match="not a valid zip"):
            extract_krpc_zip(bad_zip, ksp_dir)

    def test_raises_on_missing_krpc_dll(self, tmp_path: Path) -> None:
        """If the zip doesn't contain GameData/kRPC/kRPC.dll, it's not a real kRPC release."""
        ksp_dir = tmp_path / "ksp"
        ksp_dir.mkdir()

        zip_path = tmp_path / "wrong.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("SomeOtherMod/mod.dll", b"wrong mod")

        with pytest.raises(KrpcInstallError, match="does not contain kRPC"):
            extract_krpc_zip(zip_path, ksp_dir)


class TestGetLatestKrpcDownloadUrl:
    """Tests for fetching the kRPC download URL from GitHub."""

    @pytest.mark.asyncio
    async def test_returns_url_and_version(self) -> None:
        """Should return the download URL for the zip asset and the version tag."""
        fake_response = Mock()
        fake_response.json.return_value = {
            "tag_name": "v0.5.4",
            "assets": [
                {
                    "name": "krpc-0.5.4.zip",
                    "browser_download_url": "https://github.com/krpc/krpc/releases/download/v0.5.4/krpc-0.5.4.zip",
                },
                {
                    "name": "krpc-0.5.4-python.zip",
                    "browser_download_url": "https://github.com/krpc/krpc/releases/download/v0.5.4/krpc-0.5.4-python.zip",
                },
            ],
        }

        fake_client = AsyncMock()
        fake_client.get.return_value = fake_response

        url, version = await get_latest_krpc_download_url(client=fake_client)
        assert version == "v0.5.4"
        assert "krpc-0.5.4.zip" in url
        # Should pick the main zip, not the python client zip
        assert "python" not in url

    @pytest.mark.asyncio
    async def test_raises_when_no_zip_asset(self) -> None:
        """Should raise if no suitable .zip asset is found in the release."""
        fake_response = Mock()
        fake_response.json.return_value = {
            "tag_name": "v1.0.0",
            "assets": [
                {"name": "source.tar.gz", "browser_download_url": "https://example.com/src.tar.gz"},
            ],
        }

        fake_client = AsyncMock()
        fake_client.get.return_value = fake_response

        with pytest.raises(KrpcInstallError, match="No suitable kRPC download"):
            await get_latest_krpc_download_url(client=fake_client)

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self) -> None:
        """Should wrap HTTP errors in KrpcInstallError."""
        import httpx

        fake_client = AsyncMock()
        fake_client.get.side_effect = httpx.HTTPError("connection failed")

        with pytest.raises(KrpcInstallError, match="Failed to fetch"):
            await get_latest_krpc_download_url(client=fake_client)


class TestInstallKrpc:
    """Tests for the full install_krpc flow."""

    @pytest.mark.asyncio
    async def test_download_and_extract(self, tmp_path: Path) -> None:
        """Full flow: download zip bytes, extract, verify."""
        ksp_dir = tmp_path / "ksp"
        (ksp_dir / "GameData").mkdir(parents=True)

        # Build a real zip in memory
        zip_path = tmp_path / "krpc.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("GameData/kRPC/kRPC.dll", b"fake-dll")
            zf.writestr("GameData/kRPC/plugin.cfg", b"cfg")
        zip_bytes = zip_path.read_bytes()

        # Mock the URL fetch and download
        fake_url_response = Mock()
        fake_url_response.json.return_value = {
            "tag_name": "v0.5.4",
            "assets": [
                {
                    "name": "krpc-0.5.4.zip",
                    "browser_download_url": "https://example.com/krpc.zip",
                },
            ],
        }

        fake_download_response = Mock()
        fake_download_response.content = zip_bytes

        fake_client = AsyncMock()
        fake_client.get.side_effect = [fake_url_response, fake_download_response]

        version = await install_krpc(ksp_dir, client=fake_client)
        assert version == "v0.5.4"
        assert (ksp_dir / "GameData" / "kRPC" / "kRPC.dll").is_file()
