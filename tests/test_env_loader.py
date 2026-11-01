import pytest

from modules.core.env_loader import (
    get_optional_env,
    get_required_env,
    load_env_file,
)


def test_load_env_file_parses_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "PLAIN=abc\n"
        'QUOTED="hello world"\n'
        "SINGLE='x=y'\n"
        "\n"
        "NOEQUALS\n",
        encoding="utf-8",
    )
    for key in ("PLAIN", "QUOTED", "SINGLE"):
        monkeypatch.delenv(key, raising=False)

    load_env_file(env)

    assert get_required_env("PLAIN") == "abc"
    assert get_required_env("QUOTED") == "hello world"
    assert get_required_env("SINGLE") == "x=y"


def test_load_env_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_env_file(tmp_path / "nope.env")


def test_required_and_optional(monkeypatch):
    monkeypatch.setenv("EMPTY_ONE", "   ")
    monkeypatch.delenv("MISSING_ONE", raising=False)

    with pytest.raises(RuntimeError):
        get_required_env("EMPTY_ONE")

    assert get_optional_env("EMPTY_ONE", "fallback") == "fallback"
    assert get_optional_env("MISSING_ONE") is None
