from __future__ import annotations

import pytest

from app.adapters.api_error import find_api_error_code


@pytest.mark.parametrize(
    "payload",
    [
        {"response": {"header": {"resultCode": "00"}}},
        {"response": {"header": {"resultCode": "03"}}},
        {"SeoulData": {"RESULT": {"CODE": "INFO-000"}}},
        {"SeoulData": {"RESULT": {"CODE": "INFO-200"}}},
    ],
)
def test_api_success_and_no_data_codes_are_not_errors(payload: dict) -> None:
    assert find_api_error_code(payload) is None


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"response": {"header": {"resultCode": "99"}}}, "99"),
        ({"RESULT_CODE": "30"}, "30"),
        ({"returnReasonCode": "22"}, "22"),
        ({"SeoulData": {"RESULT": {"CODE": "ERROR-301"}}}, "ERROR-301"),
    ],
)
def test_api_error_codes_are_found_in_nested_envelopes(
    payload: dict,
    expected: str,
) -> None:
    assert find_api_error_code(payload) == expected


def test_api_error_message_is_not_returned_as_part_of_code() -> None:
    payload = {
        "RESULT": {
            "CODE": "ERROR-301",
            "MESSAGE": "invalid key SECRET-SERVICE-KEY",
        }
    }

    code = find_api_error_code(payload)

    assert code == "ERROR-301"
    assert "SECRET-SERVICE-KEY" not in code
