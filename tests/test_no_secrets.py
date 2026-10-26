"""No credential-looking string may be committed. Runs over every file git tracks (the repo is meant to be shareable).

The patterns cover the common key formats, including OpenAI project keys ("sk-proj-..."), which an earlier ad-hoc
scan in this project missed because its pattern did not allow the hyphen after "proj". Only file names and pattern
names are reported, never the matched text.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "openai key": re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    "anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "hugging face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "github token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{30,}"),
    "aws access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "bearer token literal": re.compile(r"Bearer [0-9a-f]{32,}"),
}


def test_patterns_catch_the_formats_they_are_meant_for():
    fake = {"openai key": "sk-proj-" + "Ab1_" * 10, "github token": "ghp_" + "x" * 36, "hugging face token": "hf_" + "Q" * 34}
    for name, text in fake.items():
        assert PATTERNS[name].search(text), name
    assert not PATTERNS["openai key"].search("risk-assessment-and-mitigation-plan")  # \b keeps ordinary words out


@pytest.mark.skipif(not shutil.which("git"), reason="git not available")
def test_no_tracked_file_contains_a_credential():
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.split("\0")
    hits = []
    for rel in filter(None, files):
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        text = path.read_bytes().decode("utf-8", "replace")
        hits += [f"{rel}: {name}" for name, pat in PATTERNS.items() if pat.search(text)]
    assert not hits, hits
