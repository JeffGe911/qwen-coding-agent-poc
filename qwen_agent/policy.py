"""Deliberately narrow Python subset; defense in depth, NOT an OS sandbox.

Policy revision 2 (2026-10-23, before the report_pass_rate blind run): allows
try/except with KeyError/TypeError/ValueError and a few plain container
methods (add, copy, setdefault, update, pop, sort). The system prompt
is generated from these constants so the model is told the same contract.
Revision 1 runs (clamp/chunked/normalize_names/test_summary) used the older list.
"""
import ast
import builtins
import hashlib
import json

MAX_CODE_BYTES = 12_000
SAFE_NAMES = (
    "abs all any bool dict enumerate float int isinstance len list max min range "
    "reversed round set sorted str sum tuple zip ValueError TypeError KeyError"
).split()
SAFE_METHODS = set("append extend count index lower upper strip lstrip rstrip split join replace startswith endswith isalnum isalpha isdigit get keys values items add copy setdefault update pop sort".split())
POLICY_REVISION = 2
ALLOWED = {
    "Module", "FunctionDef", "arguments", "arg", "Return", "Assign", "AugAssign",
    "Expr", "If", "For", "Break", "Continue", "Pass", "Raise", "Assert",
    "Try", "ExceptHandler",
    "Name", "Load", "Store", "Constant", "List", "Tuple", "Dict", "Set",
    "Subscript", "Slice", "BinOp", "UnaryOp", "BoolOp", "Compare", "IfExp",
    "Call", "keyword", "Attribute", "ListComp", "SetComp", "DictComp",
    "GeneratorExp", "comprehension", "JoinedStr", "FormattedValue",
    "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod", "USub", "UAdd", "Not",
    "And", "Or", "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "In", "NotIn",
    "Is", "IsNot",
}


class PolicyError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate(code):
    if not isinstance(code, str) or len(code.encode()) > MAX_CODE_BYTES:
        raise PolicyError("Code must be a string of at most 12000 bytes")
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError) as exc:
        raise PolicyError(f"Invalid Python: {exc}") from exc
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    for statement in tree.body:
        if not isinstance(statement, ast.FunctionDef) and not (
            isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            raise PolicyError("Only function definitions and a module docstring are allowed")
    for node in ast.walk(tree):
        if type(node).__name__ not in ALLOWED:
            raise PolicyError(f"Forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise PolicyError("Private/dunder identifiers are forbidden")
        if isinstance(node, ast.arg) and node.arg.startswith("_"):
            raise PolicyError("Private/dunder arguments are forbidden")
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("_") or node.decorator_list or node.returns:
                raise PolicyError("Private functions, decorators and annotations are forbidden")
            if node.args.defaults or any(node.args.kw_defaults) or any(a.annotation for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs):
                raise PolicyError("Function defaults and annotations are forbidden")
        if isinstance(node, ast.Attribute) and node.attr not in SAFE_METHODS:
            raise PolicyError(f"Forbidden attribute: {node.attr}")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id not in set(SAFE_NAMES) | functions:
                    raise PolicyError(f"Forbidden call: {node.func.id}")
            elif not isinstance(node.func, ast.Attribute):
                raise PolicyError("Indirect calls are forbidden")
    try:
        compile(tree, "solution.py", "exec")
    except (SyntaxError, RecursionError) as exc:
        raise PolicyError(f"Python compile failed: {exc}") from exc
    return tree


def describe():
    """Human/model-readable statement of exactly what validate() accepts."""
    return (
        "Allowed: function definitions only (plus an optional module docstring); if/for/try-except/raise/return; "
        "comprehensions; f-strings. Allowed builtin names: " + ", ".join(SAFE_NAMES) + ". "
        "Allowed methods: " + ", ".join(sorted(SAFE_METHODS)) + ". "
        "Forbidden: import, while, lambda, class, with, decorators, annotations, default arguments, "
        "names starting with underscore, any other builtin or method, module-level statements."
    )


def safe_builtins():
    return {name: getattr(builtins, name) for name in SAFE_NAMES}

