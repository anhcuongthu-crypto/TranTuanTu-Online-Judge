"""TranTu Test Generator Pro: generate, validate, and mutation-test OJ cases.

Example:
  python tools/testgen_pro.py PROBLEM.json tools.test_generators.xau_ky_tu \
      --seed 20261113 --output PROBLEM.generated.json \
      --candidate brute="python brute.py" --candidate mutant1="./mutant1"

Candidate programs receive each case on stdin. Their stdout is compared with
the trusted expected output using whitespace-insensitive token comparison.
"""
import argparse
import importlib
import json
import random
import shlex
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_problem(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValueError("Input JSON must be an array containing exactly one problem.")
    problem = data[0]
    subtasks = problem.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        raise ValueError("Problem must contain a non-empty subtasks array.")
    ids = [str(s.get("id", "")) for s in subtasks]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("Subtask IDs must be non-empty and unique.")
    total = float(problem.get("total_score", 0))
    subtotal = sum(float(s.get("score", 0)) for s in subtasks)
    if total <= 0 or abs(total - subtotal) > 1e-7:
        raise ValueError(f"Subtask scores sum to {subtotal}, expected total_score={total}.")
    for subtask in subtasks:
        tests = subtask.get("tests", [])
        if not isinstance(tests, list):
            raise ValueError(f"Subtask {subtask['id']} tests must be an array.")
        for i, test in enumerate(tests, 1):
            if not isinstance(test.get("input"), str) or not isinstance(test.get("output"), str):
                raise ValueError(f"Invalid existing test {subtask['id']}#{i}.")
    return data, {str(s["id"]): s for s in subtasks}


def normalize_output(value):
    return " ".join(str(value).split())


def parse_candidate(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("Candidate format must be NAME=COMMAND.")
    name, command = value.split("=", 1)
    if not name.strip() or not command.strip():
        raise argparse.ArgumentTypeError("Candidate name and command cannot be empty.")
    return name.strip(), shlex.split(command)


def run_candidate(command, input_text, timeout):
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            command, input=input_text, text=True, capture_output=True,
            timeout=timeout, cwd=ROOT
        )
        elapsed = time.perf_counter() - started
        if proc.returncode != 0:
            return {"kind": "RE", "elapsed": elapsed,
                    "detail": (proc.stderr or proc.stdout)[-1500:]}
        return {"kind": "OK", "elapsed": elapsed, "stdout": proc.stdout}
    except subprocess.TimeoutExpired as exc:
        return {"kind": "TLE", "elapsed": timeout,
                "detail": str(exc)[:1000]}
    except OSError as exc:
        return {"kind": "ERROR", "elapsed": time.perf_counter() - started,
                "detail": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="TranTu Test Generator Pro")
    parser.add_argument("problem_json")
    parser.add_argument("generator", help="Python module exposing generate(rng), optionally solve(input)")
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--output", help="Generated JSON destination; defaults to <input>.generated.json")
    parser.add_argument("--candidate", action="append", type=parse_candidate, default=[],
                        metavar="NAME=COMMAND", help="Candidate executable; repeat to test mutants")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="Seconds allowed per candidate per test (default: 2)")
    parser.add_argument("--report", help="JSON report destination")
    parser.add_argument("--dedupe", action="store_true",
                        help="Skip generated inputs already present in the same subtask")
    args = parser.parse_args()

    if args.timeout <= 0:
        raise ValueError("--timeout must be positive.")

    source = Path(args.problem_json)
    output = Path(args.output) if args.output else source.with_name(source.stem + ".generated.json")
    data, subtask_map = load_problem(source)
    problem = data[0]
    module = importlib.import_module(args.generator)
    generate = getattr(module, "generate", None)
    if not callable(generate):
        raise ValueError("Generator module must define generate(rng).")

    generated = list(generate(random.Random(args.seed)))
    if not generated:
        raise ValueError("Generator returned no cases.")

    existing = {
        sid: {test["input"] for test in subtask.get("tests", [])}
        for sid, subtask in subtask_map.items()
    }
    added = []
    skipped = 0
    for index, case in enumerate(generated, 1):
        if not isinstance(case, dict):
            raise ValueError(f"Generated case #{index} is not an object.")
        sid, input_text = str(case.get("subtask_id", "")), case.get("input")
        if sid not in subtask_map:
            raise ValueError(f"Generated case #{index} refers to unknown subtask {sid!r}.")
        if not isinstance(input_text, str) or not input_text.strip():
            raise ValueError(f"Generated case #{index} has empty input.")
        expected = case.get("output")
        if expected is None:
            solve = getattr(module, "solve", None)
            if not callable(solve):
                raise ValueError("Cases need output or generator module must define solve(input_text).")
            expected = solve(input_text)
        if not isinstance(expected, str):
            expected = str(expected)
        if args.dedupe and input_text in existing[sid]:
            skipped += 1
            continue
        existing[sid].add(input_text)
        added.append((sid, {"input": input_text, "output": expected}))

    if not added:
        raise ValueError("No new cases to append (all were duplicates).")

    # Verify generated reference outputs are reproducible when a solve() exists.
    solve = getattr(module, "solve", None)
    if callable(solve):
        for i, (sid, test) in enumerate(added, 1):
            reference = solve(test["input"])
            if normalize_output(reference) != normalize_output(test["output"]):
                raise ValueError(f"Reference output mismatch in generated case #{i}, subtask {sid}.")

    for sid, test in added:
        subtask_map[sid].setdefault("tests", []).append(test)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "problem_id": problem.get("id"),
        "seed": args.seed,
        "generated": len(generated),
        "added": len(added),
        "duplicates_skipped": skipped,
        "by_subtask": dict(Counter(sid for sid, _ in added)),
        "candidates": {}
    }

    if args.candidate:
        for name, command in args.candidate:
            if name in report["candidates"]:
                raise ValueError(f"Duplicate candidate name: {name}")
            stats = {"passed": 0, "killed": 0, "tle": 0, "errors": 0, "failures": []}
            for case_index, (sid, test) in enumerate(added, 1):
                result = run_candidate(command, test["input"], args.timeout)
                if result["kind"] == "OK":
                    if normalize_output(result["stdout"]) == normalize_output(test["output"]):
                        stats["passed"] += 1
                    else:
                        stats["killed"] += 1
                        stats["failures"].append({
                            "case": case_index, "subtask": sid, "kind": "WA",
                            "expected": test["output"][:1000],
                            "actual": result["stdout"][:1000]
                        })
                else:
                    key = "tle" if result["kind"] == "TLE" else "errors"
                    stats[key] += 1
                    stats["failures"].append({
                        "case": case_index, "subtask": sid,
                        "kind": result["kind"], "detail": result.get("detail", "")
                    })
            attempted = stats["passed"] + stats["killed"] + stats["tle"] + stats["errors"]
            stats["kill_rate_percent"] = round(
                100 * (stats["killed"] + stats["tle"] + stats["errors"]) / attempted, 2
            ) if attempted else 0
            report["candidates"][name] = stats

    report_path = Path(args.report) if args.report else output.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Problem: {problem.get('id', '<unknown>')}")
    print(f"Seed: {args.seed} | generated: {len(generated)} | added: {len(added)} | duplicates skipped: {skipped}")
    for sid, count in report["by_subtask"].items():
        print(f"  {sid}: +{count}")
    for name, stats in report["candidates"].items():
        print(f"Candidate {name}: passed={stats['passed']} killed={stats['killed']} "
              f"TLE={stats['tle']} errors={stats['errors']} "
              f"kill_rate={stats['kill_rate_percent']}%")
    print(f"Generated JSON: {output}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
