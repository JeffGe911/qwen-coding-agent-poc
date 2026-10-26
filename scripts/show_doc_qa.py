"""Replay saved RAG answers without loading models or executing suggestions."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    files = sorted((ROOT / "evidence/doc-qa/results/qa-v1/dev").glob("d[0-9][0-9].json"))
    print("Saved RAG development examples; incomplete run, not an accuracy benchmark.\n")
    for path in files:
        row = json.loads(path.read_text(encoding="utf-8"))
        rec, score = row["record"], row["score"]
        print(f"{row['question']['id']}  {row['question']['question']}")
        print(rec["shown"]["answer"])
        print(f"  frozen token check: {score['correct']}; gold-range overlap: {score['supported']}; {rec['seconds']} s")
        for cite in rec["shown"]["citations"]:
            print(f"  {cite['file']}:{cite['lines'][0]}-{cite['lines'][1]}\n  {cite['url']}")
        print()
    print("An existing quote is not proof that the answer is correct. See evidence/doc-qa/REPORT.md.")

if __name__ == "__main__":
    main()
