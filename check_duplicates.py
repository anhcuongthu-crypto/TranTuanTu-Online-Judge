
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROBLEMS_FILE = BASE_DIR / "data" / "problems.json"
REPORT_FILE = BASE_DIR / "duplicates_report.json"


def normalize(text):
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def main():
    if not PROBLEMS_FILE.exists():
        print("Khong tim thay data/problems.json!")
        return

    with open(PROBLEMS_FILE, "r", encoding="utf-8") as f:
        problems = json.load(f)

    if not isinstance(problems, list):
        print("Loi: problems.json phai chua mot danh sach JSON!")
        return

    groups = defaultdict(list)

    for p in problems:
        if not isinstance(p, dict):
            continue

        statement = normalize(p.get("statement", ""))

        if statement:
            groups[statement].append(p)

    duplicates = []

    for group in groups.values():
        if len(group) > 1:
            duplicates.append({
                "statement": group[0].get("statement", ""),
                "problems": [
                    {
                        "id": p.get("id"),
                        "title": p.get("title"),
                        "difficulty": p.get("difficulty"),
                        "category": p.get("category"),
                        "total_score": p.get("total_score"),
                        "test_count": sum(
                            len(st.get("tests", []))
                            for st in p.get("subtasks", [])
                            if isinstance(st, dict)
                        )
                    }
                    for p in group
                ]
            })

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            duplicates,
            f,
            ensure_ascii=False,
            indent=2
        )

    print("Tong so bai:", len(problems))
    print("So nhom bai trung:", len(duplicates))
    print("Da tao bao cao:", REPORT_FILE.name)
    print("Khong co bai nao bi xoa.")


if __name__ == "__main__":
    main()
