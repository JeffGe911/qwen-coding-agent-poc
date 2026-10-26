"""Knowledge-base documents -> section-aware chunks that remember their physical line range in the source file.

Markdown headings (#...) and reStructuredText headings (a title underlined, optionally also overlined, by a run of one
punctuation character) start sections; heading levels follow the order in which each style first appears, as in
docutils. Inside a section, blank-line-separated blocks are packed into chunks of at most MAX_CHARS characters, so a
citation can always be shown as file + section + lines.
"""
import json
from pathlib import Path
import re

CHUNKER_VERSION = "chunker-v1"
MAX_CHARS = 1200
NOT_KNOWLEDGE = ("LICENSE", "COPYING", "docs/guide/copyright.rst")  # license texts are kept with the corpus, not indexed
MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
RST_RULE = re.compile(r"^([=\-~^\"*+#`:'.])\1{2,}\s*$")


def documents(root):
    manifest = json.loads((Path(root) / "knowledge" / "MANIFEST.json").read_text(encoding="utf-8"))
    return [e for e in manifest["files"] if e["path"] not in NOT_KNOWLEDGE]


def headings(lines, markdown):
    """[(line_index, level, title)] for every heading line (0-based index of the title line)."""
    out, fence, styles = [], False, []
    for i, line in enumerate(lines):
        if markdown:
            if line.lstrip().startswith("```"):
                fence = not fence
            m = None if fence else MD_HEADING.match(line)
            if m:
                out.append((i, len(m.group(1)), m.group(2)))
            continue
        if i + 1 < len(lines) and line.strip() and not RST_RULE.match(line) and RST_RULE.match(lines[i + 1]) \
                and len(lines[i + 1].strip()) >= len(line.strip()):
            over = i > 0 and RST_RULE.match(lines[i - 1]) is not None and lines[i - 1].strip()[:1] == lines[i + 1].strip()[:1]
            style = (lines[i + 1].strip()[0], over)
            if style not in styles:
                styles.append(style)
            out.append((i, styles.index(style) + 1, line.strip()))
    return out


def chunks(root):
    out = []
    for doc in documents(root):
        lines = (Path(root) / doc["file"]).read_text(encoding="utf-8").split("\n")
        md = doc["path"].endswith(".md")
        heads = headings(lines, md)
        title = heads[0][2] if heads else doc["path"]
        bounds = [h[0] for h in heads] + [len(lines)]
        spans = ([(0, bounds[0], [])] if bounds[0] > 0 else [])
        path = []
        for (i, level, text), end in zip(heads, bounds[1:]):
            path = [p for p in path if p[0] < level] + [(level, text)]
            spans.append((i, end, [t for _, t in path]))
        for start, end, section in spans:
            blocks, cur = [], []
            for n in range(start, end):
                if lines[n].strip() or not cur:
                    if lines[n].strip() or cur:
                        cur.append(n)
                else:
                    blocks.append(cur)
                    cur = []
            if cur:
                blocks.append(cur)
            split = []
            for b in blocks:  # a block with no blank line in it (a long table or list) is cut by lines
                piece, size = [], 0
                for n in b:
                    if piece and size + len(lines[n]) + 1 > MAX_CHARS:
                        split.append(piece)
                        piece, size = [], 0
                    piece.append(n)
                    size += len(lines[n]) + 1
                split.append(piece)
            blocks = split
            pack = []
            for b in blocks + [None]:
                size = sum(len(lines[n]) + 1 for blk in pack for n in blk)
                if b is None or (pack and size + sum(len(lines[n]) + 1 for n in b) > MAX_CHARS):
                    if pack:
                        first, last = pack[0][0], pack[-1][-1]
                        text = "\n".join(lines[first:last + 1]).strip()
                        if len(text) >= 40:  # headings alone, labels and directives carry no answer
                            out.append({"id": f"{doc['source']}:{doc['path']}:{first + 1}", "source": doc["source"], "file": doc["file"],
                                        "path": doc["path"], "document": title, "section": " > ".join(section) or title,
                                        "line_start": first + 1, "line_end": last + 1, "license": doc["license"],
                                        "url": f"https://github.com/{doc['repo']}/blob/{doc['commit']}/{doc['path']}#L{first + 1}-L{last + 1}",
                                        "text": text})
                    pack = []
                if b is not None:
                    pack.append(b)
    return out
