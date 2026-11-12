"""Validate TranTu OJ problem JSON and generated test suites.

Optional validator module contract:
    validate_input(input_text, subtask_id) -> True/None for valid, False or
    raise ValueError for invalid input.
Optional reference module contract:
    solve(input_text) -> expected output string.
"""
import argparse
import importlib
import json
import sys
from collections import Counter
from pathlib import Path


REQUIRED = ("id", "title", "statement", "input", "output", "input_format",
            "output_format", "time_limit", "memory_limit", "total_score", "subtasks")


def main():
    parser = argparse.ArgumentParser(description="Validate problem JSON and tests")
    parser.add_argument("problem_json")
    parser.add_argument("--validator", help="Optional module exposing validate_input(input, subtask_id)")
    parser.add_argument("--reference", help="Optional module exposing solve(input_text)")
    parser.add_argument("--strict-duplicates", action="store_true")
    args = parser.parse_args()

    data = json.loads(Path(args.problem_json).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("Top-level JSON must be a non-empty array.")

    validator = importlib.import_module(args.validator) if args.validator else None
    reference = importlib.import_module(args.reference) if args.reference else None
    problems = tests_total = 0
    errors, warnings = [], []

    for pi, problem in enumerate(data, 1):
        problems += 1
        prefix = f"problem[{pi}]({problem.get('id', '?')})"
        for key in REQUIRED:
            if key not in problem:
                errors.append(f"{prefix}: missing field {key}")
        if "solution" in problem:
            errors.append(f"{prefix}: forbidden solution field must not be exported")
        subtasks = problem.get("subtasks")
        if not isinstance(subtasks, list) or not subtasks:
            errors.append(f"{prefix}: subtasks must be a non-empty array")
            continue
        try:
            total = float(problem["total_score"])
            subtotal = sum(float(s["score"]) for s in subtasks)
            if abs(total - subtotal) > 1e-7:
                errors.append(f"{prefix}: subtask scores sum to {subtotal}, total_score is {total}")
        except (KeyError, TypeError, ValueError):
            errors.append(f"{prefix}: invalid score fields")

        ids = [str(s.get("id", "")) for s in subtasks]
        if any(not sid for sid in ids) or len(ids) != len(set(ids)):
            errors.append(f"{prefix}: subtask IDs must be present and unique")

        for subtask in subtasks:
            sid = str(subtask.get("id", "?"))
            cases = subtask.get("tests", [])
            if not isinstance(cases, list):
                errors.append(f"{prefix}/{sid}: tests must be an array")
                continue
            seen = set()
            for ti, case in enumerate(cases, 1):
                tests_total += 1
                label = f"{prefix}/{sid}/test[{ti}]"
                inp, out = case.get("input"), case.get("output")
                if not isinstance(inp, str) or not inp.strip():
                    errors.append(f"{label}: input must be a non-empty string")
                    continue
                if not isinstance(out, str):
                    errors.append(f"{label}: output must be a string")
                    continue
                if inp in seen:
                    msg = f"{label}: duplicate input within subtask"
                    (errors if args.strict_duplicates else warnings).append(msg)
                seen.add(inp)
                if validator:
                    fn = getattr(validator, "validate_input", None)
                    if not callable(fn):
                        raise ValueError("Validator module must define validate_input(input_text, subtask_id)")
                    try:
                        valid = fn(inp, sid)
                        if valid is False:
                            errors.append(f"{label}: validator rejected input")
                    except Exception as exc:
                        errors.append(f"{label}: invalid input: {exc}")
                if reference:
                    fn = getattr(reference, "solve", None)
                    if not callable(fn):
                        raise ValueError("Reference module must define solve(input_text)")
                    try:
                        expected = str(fn(inp))
                        if " ".join(expected.split()) != " ".join(out.split()):
                            errors.append(f"{label}: expected output differs from reference solver")
                    except Exception as exc:
                        errors.append(f"{label}: reference solver failed: {exc}")

    print(f"Problems: {problems} | Tests: {tests_total} | Errors: {len(errors)} | Warnings: {len(warnings)}")
    for item in errors:
        print("ERROR:", item)
    for item in warnings:
        print("WARNING:", item)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        raise SystemExit(2)
