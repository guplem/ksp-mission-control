"""Tests for the craft file management utilities."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ksp_mission_control.craft import (
    CraftError,
    export_craft_to_project,
    find_active_save_dir,
    find_craft_in_save,
    load_craft_into_ksp,
    sanitize_craft_name,
)


class TestSanitizeCraftName:
    """Tests for craft name sanitization."""

    def test_spaces_and_hyphens(self) -> None:
        assert sanitize_craft_name("Fart - 1") == "fart-1"

    def test_uppercase(self) -> None:
        assert sanitize_craft_name("MyRocket") == "myrocket"

    def test_special_characters(self) -> None:
        assert sanitize_craft_name("Cool Rocket!!") == "cool-rocket"

    def test_leading_trailing_whitespace(self) -> None:
        assert sanitize_craft_name("  padded  ") == "padded"

    def test_multiple_special_chars_collapse(self) -> None:
        assert sanitize_craft_name("a --- b") == "a-b"

    def test_already_clean(self) -> None:
        assert sanitize_craft_name("fart-1") == "fart-1"

    def test_numbers_preserved(self) -> None:
        assert sanitize_craft_name("Rocket 42 v2") == "rocket-42-v2"

    def test_empty_after_strip(self) -> None:
        assert sanitize_craft_name("!!!") == ""


class TestFindActiveSaveDir:
    """Tests for active save directory detection."""

    def test_finds_most_recent_save(self, tmp_path: Path) -> None:
        saves = tmp_path / "saves"
        saves.mkdir()

        old_save = saves / "OldSave"
        old_save.mkdir()
        old_sfs = old_save / "persistent.sfs"
        old_sfs.write_text("old")

        # Ensure different mtime
        time.sleep(0.05)

        new_save = saves / "NewSave"
        new_save.mkdir()
        new_sfs = new_save / "persistent.sfs"
        new_sfs.write_text("new")

        result = find_active_save_dir(tmp_path)
        assert result == new_save

    def test_ignores_dirs_without_sfs(self, tmp_path: Path) -> None:
        saves = tmp_path / "saves"
        saves.mkdir()

        no_sfs = saves / "NoSfs"
        no_sfs.mkdir()

        with_sfs = saves / "WithSfs"
        with_sfs.mkdir()
        (with_sfs / "persistent.sfs").write_text("data")

        result = find_active_save_dir(tmp_path)
        assert result == with_sfs

    def test_no_saves_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CraftError, match="saves directory not found"):
            find_active_save_dir(tmp_path)

    def test_no_sfs_files_raises(self, tmp_path: Path) -> None:
        saves = tmp_path / "saves"
        saves.mkdir()
        (saves / "EmptySave").mkdir()

        with pytest.raises(CraftError, match="No save directories"):
            find_active_save_dir(tmp_path)


class TestFindCraftInSave:
    """Tests for craft file location in a save directory."""

    def test_finds_craft(self, tmp_path: Path) -> None:
        vab = tmp_path / "Ships" / "VAB"
        vab.mkdir(parents=True)
        craft = vab / "Fart - 1.craft"
        craft.write_text("ship = Fart - 1")

        result = find_craft_in_save(tmp_path, "Fart - 1")
        assert result == craft

    def test_missing_craft_raises(self, tmp_path: Path) -> None:
        vab = tmp_path / "Ships" / "VAB"
        vab.mkdir(parents=True)

        with pytest.raises(CraftError, match="Craft file not found"):
            find_craft_in_save(tmp_path, "NonExistent")


class TestExportCraftToProject:
    """Tests for exporting craft files into the project crafts directory."""

    def test_copies_with_sanitized_name(self, tmp_path: Path) -> None:
        source = tmp_path / "Fart - 1.craft"
        source.write_text("ship = Fart - 1")
        crafts = tmp_path / "crafts"

        result = export_craft_to_project(source, crafts)

        assert result == crafts / "fart-1.craft"
        assert result.read_text() == "ship = Fart - 1"

    def test_creates_crafts_dir(self, tmp_path: Path) -> None:
        source = tmp_path / "Test.craft"
        source.write_text("data")
        crafts = tmp_path / "crafts"

        export_craft_to_project(source, crafts)
        assert crafts.is_dir()

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        source = tmp_path / "Test.craft"
        source.write_text("new content")
        crafts = tmp_path / "crafts"
        crafts.mkdir()
        (crafts / "test.craft").write_text("old content")

        export_craft_to_project(source, crafts)
        assert (crafts / "test.craft").read_text() == "new content"

    def test_empty_name_raises(self, tmp_path: Path) -> None:
        source = tmp_path / "!!!.craft"
        source.write_text("data")

        with pytest.raises(CraftError, match="Cannot sanitize"):
            export_craft_to_project(source, tmp_path / "crafts")


class TestLoadCraftIntoKsp:
    """Tests for loading project craft files into a KSP save."""

    def test_copies_to_vab(self, tmp_path: Path) -> None:
        crafts = tmp_path / "crafts"
        crafts.mkdir()
        (crafts / "fart-1.craft").write_text("ship data")

        save_dir = tmp_path / "save"
        save_dir.mkdir()

        result = load_craft_into_ksp(crafts, "fart-1", save_dir)

        assert result == "fart-1"
        assert (save_dir / "Ships" / "VAB" / "fart-1.craft").read_text() == "ship data"

    def test_creates_vab_dir(self, tmp_path: Path) -> None:
        crafts = tmp_path / "crafts"
        crafts.mkdir()
        (crafts / "test.craft").write_text("data")

        save_dir = tmp_path / "save"
        save_dir.mkdir()

        load_craft_into_ksp(crafts, "test", save_dir)
        assert (save_dir / "Ships" / "VAB").is_dir()

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        crafts = tmp_path / "crafts"
        crafts.mkdir()

        with pytest.raises(CraftError, match="not found in project"):
            load_craft_into_ksp(crafts, "missing", tmp_path / "save")
