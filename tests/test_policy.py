import pytest
from qwen_agent.policy import PolicyError, safe_builtins, validate


@pytest.mark.parametrize("code", [
    "import os", "def f():\n import socket", "def f():\n return open('x')",
    "def f():\n return eval('1')", "def f():\n return exec('x=1')",
    "def f(x):\n return x.__class__", "def f():\n return globals()",
    "def f():\n return __import__('os')", "def f():\n return getattr(str, 'x')",
    "def f():\n while True: pass", "class X: pass", "x = 1",
    "@print\ndef f():\n return 1", "def f(x=open('x')):\n return x",
    "def f(x: open('x')):\n return x", "def f():\n return (lambda: 1)()",
    "def f(x):\n return x.format()", "def f(x):\n return x[0]()",
    "def f():\n return 2 ** 999999999", "def f():\n return print('x')",
    "def f():\n break",
])
def test_dangerous_syntax_blocked(code):
    with pytest.raises(PolicyError):
        validate(code)


def test_safe_code_runs_with_restricted_builtins():
    code = "def f(names):\n return [x.strip().lower() for x in names if x.strip()]"
    scope = {"__builtins__": safe_builtins()}
    exec(compile(validate(code), "solution.py", "exec"), scope)
    assert scope["f"]([" A ", " "]) == ["a"]
    assert "open" not in scope["__builtins__"]


def test_size_limit():
    with pytest.raises(PolicyError):
        validate("#" * 12001)



def test_revision2_try_except_keyerror_is_allowed_and_runs():
    code = "def f(d):\n    try:\n        return d['status']\n    except KeyError as exc:\n        raise ValueError('missing') from exc\n"
    scope = {"__builtins__": safe_builtins()}
    exec(compile(validate(code), "solution.py", "exec"), scope)
    assert scope["f"]({"status": 1}) == 1
    with pytest.raises(ValueError):
        scope["f"]({})


@pytest.mark.parametrize("code", [
    "def f(x):\n    try:\n        return x\n    except KeyError:\n        return x.__class__",
    "def f(x):\n    return '{0.__class__}'.format(x)",
    "def f():\n    try:\n        pass\n    except* KeyError:\n        pass",
])
def test_revision2_still_blocks_reflection_and_format(code):
    with pytest.raises(PolicyError):
        validate(code)
