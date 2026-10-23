import pytest
from solution import chunked


@pytest.mark.parametrize("size", [True, False, 1.5, "2", None])
def test_non_integer_size(size):
    with pytest.raises(ValueError):
        chunked([1, 2], size)


def test_no_mutation():
    source = [1, 2, 3]
    result = chunked(source, 8)
    assert result == [[1, 2, 3]]
    result[0].append(4)
    assert source == [1, 2, 3]


def test_exact_multiple():
    assert chunked([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]
