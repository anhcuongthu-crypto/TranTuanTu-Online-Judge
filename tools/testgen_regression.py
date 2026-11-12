"""Compare two problem JSON files and report lost/changed regression tests."""
import argparse
import json
from pathlib import Path


def load(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: top-level JSON must be an array")
    result = {}
    for problem in data:
        pid = str(problem.get("id", ""))
        if not pid:
            raise ValueError(f"{path}: problem without id")
        for subtask in problem.get("subtasks", []):
            sid = str(subtask.get("id", ""))
            for test in subtask.get("tests", []):
                key = (pid, sid, test.get("input", ""))
                result[key] = test.get("output", "")
    return result


def main():
    p = argparse.ArgumentParser(description="Check regression tests between JSON versions")
    p.add_argument("baseline")
    p.add_argument("current")
    args = p.parse_args()
    old, new = load(args.baseline), load(args.current)
    missing = [(k, v) for k, v in old.items() if k not in new]
    changed = [(k, v, new[k]) for k, v in old.items() if k in new and v != new[k]]
    print(f"Baseline tests: {len(old)} | Current tests: {len(new)}")
    print(f"Missing: {len(missing)} | Changed outputs: {len(changed)}")
    for (pid, sid, input_text), expected in missing[:20]:
        print(f"MISSING [{pid}/{sid}] input={input_text[:160]!r} expected={expected[:160]!r}")
    for (pid, sid, input_text), before, after in changed[:20]:
        print(f"CHANGED [{pid}/{sid}] input={input_text[:160]!r} before={before[:120]!r} after={after[:120]!r}")
    raise SystemExit(1 if missing or changed else 0)


if __name__ == "__main__":
    main()
