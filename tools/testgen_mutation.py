"""Run known-wrong candidate programs against an existing problem JSON test set."""
import argparse
import json
import shlex
import subprocess
from pathlib import Path


def norm(text):
    return " ".join(text.split())


def main():
    p = argparse.ArgumentParser(description="Mutation-test a solution against stored tests")
    p.add_argument("problem_json")
    p.add_argument("--candidate", action="append", required=True, metavar="NAME=COMMAND")
    p.add_argument("--timeout", type=float, default=2.0)
    args = p.parse_args()
    if args.timeout <= 0:
        p.error("--timeout must be positive")
    data = json.loads(Path(args.problem_json).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        p.error("problem JSON must be a top-level array")
    tests = []
    for problem in data:
        for subtask in problem.get("subtasks", []):
            for test in subtask.get("tests", []):
                tests.append((str(problem.get("id")), str(subtask.get("id")),
                              test["input"], test["output"]))
    if not tests:
        p.error("no tests found")
    for item in args.candidate:
        if "=" not in item:
            p.error("candidate must use NAME=COMMAND")
        name, command = item.split("=", 1)
        argv = shlex.split(command)
        if not name or not argv:
            p.error("candidate name and command cannot be empty")
        passed = killed = tle = errors = 0
        for index, (pid, sid, inp, expected) in enumerate(tests, 1):
            try:
                proc = subprocess.run(argv, input=inp, text=True, capture_output=True,
                                      timeout=args.timeout)
                if proc.returncode != 0:
                    errors += 1
                elif norm(proc.stdout) == norm(expected):
                    passed += 1
                else:
                    killed += 1
                    print(f"{name}: killed by WA at test #{index} ({pid}/{sid})")
            except subprocess.TimeoutExpired:
                tle += 1
                print(f"{name}: killed by TLE at test #{index} ({pid}/{sid})")
            except OSError as exc:
                raise SystemExit(f"Cannot run {name}: {exc}")
        total = len(tests)
        rate = 100.0 * (killed + tle + errors) / total
        print(f"{name}: pass={passed}, WA={killed}, TLE={tle}, RE/ERR={errors}, kill-rate={rate:.2f}%")
if __name__ == "__main__":
    main()
