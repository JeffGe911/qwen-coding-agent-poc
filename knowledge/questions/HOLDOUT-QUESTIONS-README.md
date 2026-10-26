# Doc-QA holdout question set (`holdout.jsonl`)

A blind evaluation set for the offline document question-answering system. It has
40 questions about the documents in `knowledge/` (listed in `knowledge/MANIFEST.json`).
The system must answer each question from that knowledge base with citations, or say
that the answer is not in it.

## How it was built

A separate session wrote the set, working only from a written brief. That session
never saw the doc-QA system, its prompts, its retrieval index, its tests or its
earlier results. It read the corpus documents directly, wrote the questions
and gold annotations by hand, and checked every annotation against the corpus with
a script kept outside the repo. It did not call any language model or API, and it
used no network.

### Independence rules

Allowed reading: everything under `knowledge/`, except `knowledge/questions/dev.jsonl`
and anything under `knowledge/index/`. In practice, that meant `knowledge/MANIFEST.json`
and the corpus files under `knowledge/lowrisc-style-guides/`, `knowledge/verilator/`
and `knowledge/icarus-verilog/`.

Not read: the `doc_qa/` package, `regression_triage/`, `qwen_agent/`, `tests/`,
`scripts/`, `evidence/`, README files, `knowledge/questions/dev.jsonl` and
`knowledge/index/`.

Deviations: none. Some notes:

- `knowledge/questions/` did not exist when the session started. It appeared during
  the session, with `dev.jsonl` inside. `dev.jsonl` was never opened, so the holdout
  questions were not written with the dev questions in view, and overlap between the
  two sets was not checked.
- The session's environment summary listed some untracked path names from
  `git status`, such as `evidence/doc-qa/` and `scripts/fetch_knowledge.py`. Those
  files were not opened.
- The only repo files written were `holdout.jsonl` and this README. No existing file
  was changed, and nothing was committed.

## Format

One JSON object per line:

```
{"id": "q01", "question": "...", "language": "en|zh", "answerable": true|false,
 "gold_facts": ["..."], "gold_sources": [{"file": "knowledge/...", "lines": [start, end]}],
 "notes": "..."}
```

- `gold_facts`: 1-3 short literal strings that a correct answer must contain, in
  either language. Examples are option or flag names, keywords, system-task names,
  macro names and numbers. Each one appears verbatim in the union of the item's
  cited lines. They were chosen to survive translation: none is an ordinary English
  word that a Chinese answer would translate.
- `gold_sources`: the corpus file or files with the answer. Line ranges are 1-based,
  inclusive physical lines of the files at the commits recorded in `MANIFEST.json`.
  Some facts appear in more than one place. In that case, every place found is
  listed. A correct citation of some other passage that says the same thing may
  still exist.
- Unanswerable items have `gold_facts: []` and `gold_sources: []`. Their `notes` say
  why the answer is absent and what was searched.
- `notes` hold the expected answer for answerable items. Do not show them to the
  system under test.

## Question mix

| | English | Chinese | Total |
| --- | ---: | ---: | ---: |
| Answerable | 18 | 10 | 28 |
| Unanswerable | 9 | 3 | 12 |
| Total | 27 | 13 | 40 |

Answerable questions by source group:

| Source group | Questions |
| --- | ---: |
| lowRISC style guides (6 Verilog coding style, 4 DV coding style) | 10 |
| Verilator guide | 9 |
| Icarus Verilog usage docs | 7 |
| Cross-source (lowRISC + Verilator: 1, Verilator + Icarus: 1) | 2 |

Answerable questions by difficulty:

- 13 single facts: an option name, a rule, a default, or a version.
- 6 why or when questions, answered in one or two sentences of one passage.
- 9 multi-passage questions, needing two nearby passages in one file or passages
  from two or three files.

The questions are phrased the way engineers ask them, mostly as situations or
problems, not copied doc sentences. Answerable and unanswerable items are
interleaved, so position gives nothing away.

Unanswerable questions by kind:

- 7 near misses: same topic as something in the corpus, but the detail asked for
  is absent. Examples are an option that does not exist, a value or limit the docs
  never state, and a version requirement the docs never give. Several are built to
  catch answers borrowed from the wrong tool or the wrong option: a related passage
  exists, but for a different tool or setting.
- 1 about a commercial simulator's option.
- 1 about a tool version that the corpus does not cover.
- 2 clearly outside chip-verification tool documentation.
- 1 that tells the system to ignore its sources and answer from its own knowledge.
  That answer is not in the corpus either.

## How unanswerability was checked

For each unanswerable item, the key terms were searched with case-insensitive
`grep` across all three corpus directories. The terms were the option or flag
spelling, the tool or vendor name, any version string, and plain-language synonyms
of the requested detail. Every hit was then read in context. An item was kept only
when the hits did not contain the requested detail. For example, a hit was not
enough when the passage covered the same mechanism but never gave the value asked
for. The `notes` of each item record what was searched and what the closest real
passage says.

For the version question, every version string in the relevant docs was listed,
to confirm that the version asked about is not covered.

## Validation

A checker outside the repo was run on the final file before hand-off, and it passed. It checks that:

- every line parses as a JSON object with exactly the fields above;
- ids are unique, and `language` is `en` or `zh`;
- every `gold_sources` file exists under `knowledge/`, and its line range is valid
  for that file;
- every `gold_fact` occurs verbatim in the union of that item's cited lines;
- answerable items have 1-3 facts and at least one source;
- unanswerable items have empty facts and sources;
- the file uses LF line endings and ends with a newline.

## Integrator notes (added when the set was committed)

- The system under test (doc_qa: chunker-v1, index-v1, docqa-prompt-v1, the citation checks) was committed at
  `c62ae79`, before this set was handed over. The hand-back carried only counts; the integrator has not opened the
  questions.
- Only the `question` field reaches retrieval and the model (`doc_qa/__main__.py` eval); `gold_facts`, `gold_sources`
  and `notes` (which holds the expected answer) are used by the scorer only.
- Mechanical checks by the integrator: 40 lines parse with the required fields; every gold fact occurs in its gold
  source lines; ids and question texts do not overlap with dev.jsonl; no CR bytes.
