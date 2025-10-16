import pytest

from arkumu.common.uri_utils import normalize_text_input


def test_normalize_text_input_preserves_whitespace():
    value = " Aaron Hamm studies Product Design at the Folkwang University of the Arts. "
    assert normalize_text_input(value) == value


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", None),
        ("   ", None),
        ("\n\t", None),
        ("\u00a0", None),  # non-breaking space
        (" content ", " content "),
    ],
)
def test_normalize_text_input_blank_to_none(raw, expected):
    result = normalize_text_input(raw, blank_to_none=True)
    assert result == expected
