"""The example configuration files load (deploy/; ICD IF-10)."""

import shutil
from pathlib import Path

import pytest

from wow.app.config import (
    DEFAULT_FTP, DEFAULT_LEAD_TIME, default_static, load_config,
    load_settings,
)
from wow.app.main import app_version, parse_args
from wow.app.workout_catalog import load_builtin

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.case("S-CFG-01")
def test_the_examples_load(tmp_path: Path) -> None:
    config = load_config(ROOT / "deploy" / "wow.example.toml")
    assert (config.https_port, config.http_port) == (8443, 8080)
    assert config.static == default_static() and not config.simulate
    shutil.copy(ROOT / "deploy" / "settings.example.json",
                tmp_path / "settings.json")
    settings = load_settings(tmp_path)
    assert settings.trainer == "94:05:BB:03:5D:9D"
    assert settings.hrm == "E0:E2:EF:63:14:BC"


@pytest.mark.case("S-CFG-01")
def test_defaults_without_files(tmp_path: Path) -> None:
    (tmp_path / "wow.toml").write_text(
        '[web]\ncert = "c"\nkey = "k"\nroot_cert = "r"\nstatic = "s"\n',
        encoding="utf-8")
    config = load_config(tmp_path / "wow.toml")
    assert (config.https_port, config.host, config.adapter) == (
        443, "wow.local", "hci0")
    assert config.static == Path("s")
    settings = load_settings(tmp_path)
    assert (settings.ftp, settings.lead_time) == (DEFAULT_FTP,
                                                  DEFAULT_LEAD_TIME)
    assert settings.trainer is None and settings.hrm is None


@pytest.mark.case("S-CFG-01")
def test_command_line_and_built_ins(tmp_path: Path) -> None:
    args = parse_args(["--config", "x.toml", "--sim"])
    assert args.config == Path("x.toml") and args.sim
    assert app_version()
    refs = [w.ref for w in load_builtin()]
    assert refs == ["builtin:erg-check", "builtin:intervals-30-30"]
    (tmp_path / "bad.json").write_text('{"schema": 2}', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert load_builtin(tmp_path) == []
