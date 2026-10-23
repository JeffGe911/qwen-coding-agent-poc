"""Trusted pytest launcher. Candidate code never receives normal Python builtins."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import xml.etree.ElementTree as ET

from qwen_agent.policy import safe_builtins, validate


def main():
    workspace = Path(sys.argv[1]).resolve()
    code = (workspace / "solution.py").read_text(encoding="utf-8")
    tree = validate(code)
    module = types.ModuleType("solution")
    module.__dict__["__builtins__"] = safe_builtins()
    exec(compile(tree, "solution.py", "exec"), module.__dict__)
    sys.modules["solution"] = module
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest
    class VisibleFeedback:
        def __init__(self):
            self.failures = []

        def pytest_runtest_logreport(self, report):
            if report.failed and report.nodeid.split("::")[0].endswith("test_visible.py"):
                self.failures.append(str(report.longrepr)[-3000:])

    feedback = VisibleFeedback()
    with tempfile.TemporaryDirectory(prefix="qwen-pytest-") as tmp:
        xml = Path(tmp) / "results.xml"
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
            rc = pytest.main([str(workspace / "test_visible.py"), str(workspace / "test_holdout.py"), "-q", "--tb=short", "-p", "no:cacheprovider", f"--junitxml={xml}", "--confcutdir=" + str(workspace)], plugins=[feedback])
        counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        if xml.exists():
            for suite in ET.parse(xml).getroot().iter("testsuite"):
                for key in counts:
                    counts[key] += int(suite.attrib.get(key, 0))
        counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        print(json.dumps({"exit_code": int(rc), **counts, "output": capture.getvalue()[-12000:], "visible_feedback": "\n".join(feedback.failures)[-6000:]}))


if __name__ == "__main__":
    main()

