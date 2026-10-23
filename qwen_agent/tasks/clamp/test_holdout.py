import pytest
from solution import clamp


@pytest.mark.parametrize("value,low,high,want", [(1.5, 0.25, 1.25, 1.25), (-10, -5, -1, -5), (100, 3, 3, 3), (0, 0, 1, 0)])
def test_boundaries(value, low, high, want):
    assert clamp(value, low, high) == want
