import pytest

from agentic_learning_platform.config import (
    InvalidAwsConfigurationError,
    Settings,
    get_settings,
    validate_aws_configuration,
)


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


def _aws_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "runtime_mode": "aws",
        "embedding_dimension": 1024,
        "s3_bucket": "test-bucket",
    }
    defaults.update(overrides)
    # See the `_env_file=None` note above — same reasoning.
    return Settings(_env_file=None, **defaults)  # pyright: ignore[reportCallIssue]


def test_validate_aws_configuration_passes_for_a_valid_titan_dimension() -> None:
    validate_aws_configuration(_aws_settings(embedding_dimension=1024))


def test_validate_aws_configuration_rejects_a_dimension_titan_does_not_support() -> None:
    with pytest.raises(InvalidAwsConfigurationError, match="not valid"):
        validate_aws_configuration(_aws_settings(embedding_dimension=384))


def test_validate_aws_configuration_requires_an_s3_bucket() -> None:
    with pytest.raises(InvalidAwsConfigurationError, match="S3_BUCKET"):
        validate_aws_configuration(_aws_settings(s3_bucket=None))


def test_validate_aws_configuration_is_a_no_op_in_local_mode() -> None:
    # local mode keeps its 384-dimension default — never validated against
    # Titan's constraints, since Titan is never called in this mode.
    validate_aws_configuration(Settings(_env_file=None))  # pyright: ignore[reportCallIssue]
