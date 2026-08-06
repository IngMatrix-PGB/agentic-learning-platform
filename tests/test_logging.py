import json
import logging
import logging.config
import sys
from collections.abc import Iterator
from types import TracebackType

import pytest

from agentic_learning_platform.config import Settings
from agentic_learning_platform.logging import (
    UVICORN_LOGGER_NAMES,
    JsonFormatter,
    build_uvicorn_log_config,
    configure_logging,
)

# Same shape as `sys.exc_info()`'s return type.
ExcInfo = tuple[type[BaseException], BaseException, TracebackType] | tuple[None, None, None]


# Pytest discovers and invokes autouse fixtures by name via its plugin
# machinery, not through a direct call anywhere in this module, so pyright
# has no way to see this as "used" — a known false positive for pytest
# fixtures, not dead code.
@pytest.fixture(autouse=True)
def _restore_logging_state() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """`configure_logging`/`build_uvicorn_log_config` mutate global logger
    state (the root logger and uvicorn's loggers). Restore it after each test
    so this module never leaks handlers into other test files.
    """
    root_logger = logging.getLogger()
    original_root_handlers = root_logger.handlers[:]
    original_root_level = root_logger.level
    original_uvicorn_state = {
        name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate)
        for name in UVICORN_LOGGER_NAMES
    }

    yield

    root_logger.handlers = original_root_handlers
    root_logger.setLevel(original_root_level)
    for name, (handlers, propagate) in original_uvicorn_state.items():
        logger = logging.getLogger(name)
        logger.handlers = handlers
        logger.propagate = propagate


def _settings_without_env_file() -> Settings:
    # Pydantic's `dataclass_transform` makes pyright synthesize `Settings.__init__`
    # from declared fields only, so it does not see `BaseSettings`'s private
    # `_env_file` kwarg. This is a known typing limitation, not a real type error
    # (see the same note in tests/test_config.py). Centralized here so the rest
    # of this module doesn't repeat the `pyright: ignore` comment.
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def _make_record(
    *,
    logger_name: str = "test.logger",
    level: int = logging.INFO,
    message: str = "hello",
    args: tuple[object, ...] = (),
    exc_info: ExcInfo | None = None,
) -> logging.LogRecord:
    return logging.LogRecord(
        name=logger_name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=exc_info,
    )


class TestJsonFormatter:
    def test_produces_valid_json_with_expected_keys(self) -> None:
        record = _make_record(level=logging.INFO, message="hello")

        payload = json.loads(JsonFormatter().format(record))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "test.logger"
        assert payload["message"] == "hello"
        assert "timestamp" in payload
        assert "exception" not in payload

    def test_includes_exception_when_exc_info_present(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()

        record = _make_record(level=logging.ERROR, message="failed", exc_info=exc_info)

        payload = json.loads(JsonFormatter().format(record))

        assert "exception" in payload
        assert "ValueError: boom" in payload["exception"]

    def test_omits_exception_key_when_no_exc_info(self) -> None:
        record = _make_record()

        payload = json.loads(JsonFormatter().format(record))

        assert "exception" not in payload


class TestConfigureLogging:
    def test_application_logger_emits_a_single_valid_json_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = _settings_without_env_file()
        configure_logging(settings)

        logging.getLogger("agentic_learning_platform.somewhere").info("app message")

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["message"] == "app message"
        assert payload["logger"] == "agentic_learning_platform.somewhere"


class TestUvicornLogConfig:
    def test_uvicorn_loggers_lose_their_own_handlers_and_propagate(self) -> None:
        settings = _settings_without_env_file()
        configure_logging(settings)

        logging.config.dictConfig(build_uvicorn_log_config(settings))

        for name in UVICORN_LOGGER_NAMES:
            logger = logging.getLogger(name)
            assert logger.handlers == []
            assert logger.propagate is True

    def test_uvicorn_access_logger_emits_exactly_one_json_line_via_root(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = _settings_without_env_file()
        configure_logging(settings)
        logging.config.dictConfig(build_uvicorn_log_config(settings))

        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1234", "GET", "/health", "1.1", 200
        )

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1  # no duplicate emission (own handler + propagation)
        payload = json.loads(lines[0])
        assert payload["logger"] == "uvicorn.access"
        assert payload["message"] == '127.0.0.1:1234 - "GET /health HTTP/1.1" 200'

    def test_uvicorn_error_logger_also_routes_through_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = _settings_without_env_file()
        configure_logging(settings)
        logging.config.dictConfig(build_uvicorn_log_config(settings))

        logging.getLogger("uvicorn.error").info("Application startup complete.")

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["logger"] == "uvicorn.error"
        assert payload["message"] == "Application startup complete."
