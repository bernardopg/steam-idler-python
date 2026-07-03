"""Structural parity checks for the GUI configuration path."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "src" / "steam_idle_bot" / "config" / "settings.py"
GUI_PATH = ROOT / "src" / "steam_idle_bot" / "gui.py"


def _settings_fields() -> set[str]:
    tree = ast.parse(SETTINGS_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
    raise AssertionError("Settings class not found")


def _gui_settings_kwargs() -> set[str]:
    tree = ast.parse(GUI_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_settings_from_form":
            for child in ast.walk(node):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "Settings":
                    return {keyword.arg for keyword in child.keywords if keyword.arg is not None}
    raise AssertionError("GUI Settings(...) call not found")


def test_gui_builds_every_settings_field() -> None:
    assert _settings_fields() - _gui_settings_kwargs() == set()


def test_gui_worker_writes_run_transcript() -> None:
    source = GUI_PATH.read_text(encoding="utf-8")

    assert 'Path("logs") / "runs"' in source
    assert "run_{" in source
    assert "%Y%m%d_%H%M%SZ" in source
    assert "logging.FileHandler" in source
