"""Opt-in only: every test under this directory is skipped unless
``RUN_AWS_SMOKE_TESTS=1`` is set — never required by normal CI (see
pyproject.toml's ``aws_smoke`` marker registration and
docs/architecture.md's PR-008 section). Real AWS credentials
(``AWS_PROFILE``/SSO/env) and ``RUNTIME_MODE=aws`` configuration are
required to actually pass, not just to run.
"""

import os

import pytest

from agentic_learning_platform.config import (
    InvalidAwsConfigurationError,
    Settings,
    validate_aws_configuration,
)

pytestmark = pytest.mark.aws_smoke


def _require_aws_smoke() -> None:
    if os.environ.get("RUN_AWS_SMOKE_TESTS") != "1":
        pytest.skip("RUN_AWS_SMOKE_TESTS is not set — opt-in real AWS smoke test, skipped")


@pytest.fixture(autouse=True)
def _skip_unless_opted_in() -> None:  # pyright: ignore[reportUnusedFunction]
    _require_aws_smoke()


@pytest.fixture
def aws_smoke_settings() -> Settings:
    """Settings for an AWS smoke test, validated the same way the real
    application does — via ``config.validate_aws_configuration``, the
    exact function ``infrastructure.di.build_adapters`` calls before
    constructing any AWS client. Reused here, not reimplemented, so a
    misconfigured smoke-test environment (wrong embedding dimension,
    missing S3 bucket) skips with the same clear, actionable message the
    real app would fail startup with — instead of a confusing downstream
    AWS/S3 error discovered only after an API call."""
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    if settings.runtime_mode != "aws":
        pytest.skip('RUNTIME_MODE is not "aws" — set it to run this smoke test')
    try:
        validate_aws_configuration(settings)
    except InvalidAwsConfigurationError as exc:
        pytest.skip(f"AWS configuration invalid for smoke test: {exc}")
    return settings
