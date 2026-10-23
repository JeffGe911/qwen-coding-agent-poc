from solution import normalize_names


def test_clean_and_deduplicate():
    assert normalize_names([" Alice ", "BOB", "alice", "", "  "]) == ["alice", "bob"]


def test_empty():
    assert normalize_names([]) == []


def test_input_unchanged():
    source = [" Z ", "A", "z"]
    assert normalize_names(source) == ["z", "a"]
    assert source == [" Z ", "A", "z"]
