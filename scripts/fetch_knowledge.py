"""Download the public documents of the doc-QA knowledge base, each pinned to a commit, and record what was fetched.

This is the only step of the doc-QA work that uses the network. Everything after it (indexing, retrieval, answering,
evaluation) talks to 127.0.0.1 only. Files are stored byte for byte under knowledge/<source>/ and listed in
knowledge/MANIFEST.json with URL, commit, license and sha256; re-running refuses to overwrite a different file.
IEEE 1364/1800 themselves are not freely redistributable and are not included.
Usage: python scripts/fetch_knowledge.py
"""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge"
SOURCES = [
    {"name": "lowrisc-style-guides", "repo": "lowRISC/style-guides", "commit": "9c15ff5dce23eef969e00ab3715153967419eadd", "license": "CC-BY-4.0",
     "files": ["VerilogCodingStyle.md", "DVCodingStyle.md", "LICENSE"]},
    {"name": "verilator", "repo": "verilator/verilator", "commit": "ea338be98e1e838d3518809ce8899f85a009963c", "license": "LGPL-3.0-only OR Artistic-2.0",
     "tag": "v5.052", "files": [f"docs/guide/{f}.rst" for f in ("warnings", "languages", "faq", "verilating", "simulating", "exe_verilator", "control", "overview", "copyright")]},
    {"name": "icarus-verilog", "repo": "steveicarus/iverilog", "commit": "f9111a949f4a7ba6fe781c6bb4966143af352753", "license": "GPL-2.0",
     "files": [f"Documentation/usage/{f}.rst" for f in ("getting_started", "command_line_flags", "command_files", "simulation", "vvp_flags", "ivlpp_flags",
                                                         "icarus_verilog_quirks", "icarus_verilog_extensions", "verilog_attributes", "vvp_debug", "waveform_viewer")]
              + ["Documentation/developer/guide/misc/ieee1364-notes.rst", "COPYING"]},
]


def main():
    opener = urllib.request.build_opener()
    entries = []
    for src in SOURCES:
        for rel in src["files"]:
            url = f"https://raw.githubusercontent.com/{src['repo']}/{src['commit']}/{rel}"
            dest = KB / src["name"] / rel
            with opener.open(url, timeout=60) as r:
                data = r.read()
            if dest.exists() and dest.read_bytes() != data:
                raise SystemExit(f"{dest} exists with different content; refusing to overwrite")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            entries.append({"source": src["name"], "repo": src["repo"], "commit": src["commit"], "tag": src.get("tag"), "license": src["license"],
                            "path": rel, "file": dest.relative_to(ROOT).as_posix(), "url": url, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            print(f"{len(data):7d}  {dest.relative_to(ROOT).as_posix()}")
    (KB / "MANIFEST.json").write_text(json.dumps({"note": "Public documents for the offline doc-QA knowledge base; fetched once by scripts/fetch_knowledge.py.",
                                                  "files": entries}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(len(entries), "files,", sum(e["bytes"] for e in entries), "bytes")


if __name__ == "__main__":
    main()
