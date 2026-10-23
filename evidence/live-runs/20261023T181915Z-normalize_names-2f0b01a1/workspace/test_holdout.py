from solution import normalize_names


def test_unicode():
    assert normalize_names([" ÉVA ", "éva", " 张三 "]) == ["éva", "张三"]


def test_order_and_separate_list():
    source = ["b", "a", "b", "c", "a"]
    result = normalize_names(source)
    assert result == ["b", "a", "c"]
    assert result is not source


def test_whitespace():
    assert normalize_names(["\t", "\n", " A\t", "a"]) == ["a"]
