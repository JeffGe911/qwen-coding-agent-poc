import pytest
from solution import clamp


@pytest.mark.parametrize("value,low,high,want", [(-2, 0, 10, 0), (20, 0, 10, 10), (4, 0, 10, 4)])
def test_clamp(value, low, high, want):
    assert clamp(value, low, high) == want


def test_invalid_bounds():
    with pytest.raises(ValueError):
        clamp(5, 10, 0)
