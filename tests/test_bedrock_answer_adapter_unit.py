"""Unit tests for the pure helper functions inside
``BedrockAnswerGeneratorAdapter`` — content/usage extraction from a
``ChatBedrockConverse`` chunk shape, without constructing a real Bedrock
client or making a network call. Real end-to-end streaming against AWS is
covered separately by the opt-in ``aws_smoke`` tests.
"""

from agentic_learning_platform.infrastructure.answer_generation.bedrock_answer_adapter import (
    _content_to_text,  # pyright: ignore[reportPrivateUsage]
    _usage_field_as_int,  # pyright: ignore[reportPrivateUsage]
)


def test_content_to_text_passes_through_a_plain_string() -> None:
    assert _content_to_text("hola") == "hola"


def test_content_to_text_joins_a_list_of_string_parts() -> None:
    assert _content_to_text(["hola ", "mundo"]) == "hola mundo"


def test_content_to_text_stringifies_non_string_list_parts() -> None:
    assert _content_to_text([{"type": "text", "text": "x"}]) == "{'type': 'text', 'text': 'x'}"


def test_content_to_text_returns_empty_string_for_an_unexpected_shape() -> None:
    assert _content_to_text(None) == ""
    assert _content_to_text(42) == ""


def test_usage_field_as_int_extracts_a_present_integer_field() -> None:
    assert _usage_field_as_int({"input_tokens": 42}, "input_tokens") == 42


def test_usage_field_as_int_is_none_when_the_field_is_absent() -> None:
    assert _usage_field_as_int({"input_tokens": 42}, "output_tokens") is None


def test_usage_field_as_int_is_none_when_usage_is_none() -> None:
    assert _usage_field_as_int(None, "input_tokens") is None


def test_usage_field_as_int_is_none_for_a_non_int_value() -> None:
    assert _usage_field_as_int({"input_tokens": "not-a-number"}, "input_tokens") is None
