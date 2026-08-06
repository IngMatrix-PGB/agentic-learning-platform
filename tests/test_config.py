import pytest

from agentic_learning_platform.config import Settings, get_settings


def test_settings_has_sane_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("APP_NAME", "APP_ENV", "LOG_LEVEL", "APP_HOST", "APP_PORT"):
        monkeypatch.delenv(var, raising=False)

    # Pydantic's `dataclass_transform` makes pyright synthesize `Settings.__init__`
    # from declared fields only, so it does not see `BaseSettings`'s private
    # `_env_file` kwarg. This is a known typing limitation, not a real type error.
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.app_name == "agentic-learning-platform"
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.app_port == 8000


def test_settings_reads_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "custom-name")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("APP_PORT", "9000")

    # Pydantic's `dataclass_transform` makes pyright synthesize `Settings.__init__`
    # from declared fields only, so it does not see `BaseSettings`'s private
    # `_env_file` kwarg. This is a known typing limitation, not a real type error.
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.app_name == "custom-name"
    assert settings.log_level == "DEBUG"
    assert settings.app_port == 9000


def test_get_settings_returns_cached_instance() -> None:
    assert get_settings() is get_settings()
