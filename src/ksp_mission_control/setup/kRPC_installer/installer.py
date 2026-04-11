"""Download, install, and uninstall the kRPC mod in a KSP installation."""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx

KRPC_GITHUB_REPO = "krpc/krpc"
_RELEASES_API = f"https://api.github.com/repos/{KRPC_GITHUB_REPO}/releases/latest"

# Matches the main release zip (e.g. "krpc-0.5.4.zip") but not sub-packages
# like "krpc-0.5.4-python.zip".
_MAIN_ZIP_PATTERN = re.compile(r"^krpc-[\d.]+\.zip$")


class KrpcInstallError(Exception):
    """Raised when kRPC installation fails."""


def extract_krpc_zip(zip_path: Path, ksp_path: Path) -> None:
    """Extract the ``GameData/`` contents of a kRPC release zip into *ksp_path*.

    Only entries under ``GameData/`` are extracted. Other files (README, client
    zips, etc.) are silently skipped.

    Raises :class:`KrpcInstallError` if the file is not a valid zip or does not
    contain the expected kRPC files.
    """
    if not zipfile.is_zipfile(zip_path):
        raise KrpcInstallError(f"{zip_path.name} is not a valid zip file")

    with zipfile.ZipFile(zip_path) as zf:
        gamedata_entries = [n for n in zf.namelist() if n.startswith("GameData/")]
        if not any("krpc.dll" in entry.lower() for entry in gamedata_entries):
            raise KrpcInstallError(
                f"{zip_path.name} does not contain kRPC (missing GameData/kRPC/KRPC.dll)"
            )

        gamedata_dest = ksp_path / "GameData"
        gamedata_dest.mkdir(parents=True, exist_ok=True)

        for entry in gamedata_entries:
            # Strip the leading "GameData/" prefix so we extract into ksp_path/GameData/
            relative = entry[len("GameData/") :]
            if not relative:
                continue
            target = gamedata_dest / relative
            if entry.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(entry))


async def get_latest_krpc_download_url(
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    """Fetch the download URL and version tag for the latest kRPC release.

    Returns:
        A ``(download_url, version_tag)`` tuple.

    Raises:
        KrpcInstallError: If the GitHub API request fails or no suitable
            zip asset is found.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()
    try:
        response = await client.get(_RELEASES_API)  # type: ignore[union-attr]
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise KrpcInstallError(f"Failed to fetch kRPC release info: {exc}") from exc
    finally:
        if own_client:
            await client.aclose()  # type: ignore[union-attr]

    data = response.json()
    version: str = data["tag_name"]

    for asset in data.get("assets", []):
        name: str = asset["name"]
        if _MAIN_ZIP_PATTERN.match(name):
            return asset["browser_download_url"], version

    raise KrpcInstallError(
        f"No suitable kRPC download found in release {version}. "
        f"Assets: {[a['name'] for a in data.get('assets', [])]}"
    )


async def install_krpc(
    ksp_path: Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Download and install the latest kRPC mod into *ksp_path*.

    Returns the installed version tag (e.g. ``"v0.5.4"``).

    Raises:
        KrpcInstallError: On any failure (network, extraction, validation).
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(follow_redirects=True)

    try:
        url, version = await get_latest_krpc_download_url(client=client)

        try:
            response = await client.get(url)  # type: ignore[union-attr]
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise KrpcInstallError(f"Failed to download kRPC: {exc}") from exc

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = Path(tmp.name)

        try:
            extract_krpc_zip(tmp_path, ksp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    finally:
        if own_client:
            await client.aclose()  # type: ignore[union-attr]

    return version


def uninstall_krpc(ksp_path: Path) -> None:
    """Remove the kRPC mod from *ksp_path*.

    Deletes the ``GameData/kRPC/`` directory.

    Raises:
        KrpcInstallError: If the kRPC directory does not exist or removal fails.
    """
    krpc_dir = ksp_path / "GameData" / "kRPC"
    if not krpc_dir.is_dir():
        raise KrpcInstallError("kRPC is not installed")
    try:
        shutil.rmtree(krpc_dir)
    except OSError as exc:
        raise KrpcInstallError(f"Failed to remove kRPC: {exc}") from exc
