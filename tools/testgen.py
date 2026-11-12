"""Reusable test-generation runner for TranTu OJ problem JSON files.

Each problem-specific generator is a Python module exposing:
    generate(rng) -> iterable[dict]
Each yielded item contains:
    subtask_id: str
    input: str
    (optional) output: str
If output is omitted, the module must expose solve(input_text) -> str.

Run:
    python tools/testgen.py path/to/problem.json tools.test_generators.xau_ky_tu
"""
import argparse
import importlib
import json
import random
import sys
from pathlib import Path


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, list) or not data:
        raise ValueError("Problem JSON must be a non-empty top-level array.")
    return data


def validate_problem(problem):
    if not isinstance(problem, dict):
        raise ValueError("Each problem must be a JSON object.")
    subtasks = problem.get("subtasks")
    if not isinstance(subtasks, list) or not subtasks:
        raise ValueError("Problem must contain a non-empty subtasks array.")
    ids = [str(item.get("id", "")) for item in subtasks]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("Subtask IDs must be present and unique.")
    return {item["id"]: item for item in subtasks}


def normalize_case(case, module, index):
    if not isinstance(case, dict):
        raise ValueError(f"Generated case #{index} must be an object.")
    subtask_id = str(case.get("subtask_id", ""))
    input_text = case.get("input")
    if not subtask_id:
        raise ValueError(f"Generated case #{index} has no subtask_id.")
    if not isinstance(input_text, str) or not input_text.strip():
        raise ValueError(f"Generated case #{index} has empty/non-string input.")
    output_text = case.get("output")
    if output_text is None:
        solve = getattr(module, "solve", None)
        if not callable(solve):
            raise ValueError("Generator must provide output or define solve(input_text).")
        output_text = solve(input_text)
    if not isinstance(output_text, str):
        output_text = str(output_text)
    return subtask_id, {"input": input_text, "output": output_text}


def main():
    parser = argparse.ArgumentParser(description="Generate and merge OJ tests.")
    parser.add_argument("problem_json", help="JSON file containing one problem object.")
    parser.add_argument("generator", help="Import path, e.g. tools.test_generators.xau_ky_tu")
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--output", help="Output JSON path (default: overwrite input).")
    args = parser.parse_args()

    source = Path(args.problem_json)
    output = Path(args.output) if args.output else source
    data = load_json(source)
    if len(data) != 1:
        raise ValueError("Pass a JSON array containing exactly one problem.")
    problem = data[0]
    subtask_map = validate_problem(problem)
    module = importlib.import_module(args.generator)
    generate = getattr(module, "generate", None)
    if not callable(generate):
        raise ValueError("Generator module must define generate(rng).")

    rng = random.Random(args.seed)
    generated = list(generate(rng))
    if not generated:
        raise ValueError("Generator returned no test cases.")

    added = {key: 0 for key in subtask_map}
    for index, case in enumerate(generated, 1):
        subtask_id, test = normalize_case(case, module, index)
        if subtask_id not in subtask_map:
            raise ValueError(f"Unknown subtask_id {subtask_id!r} in case #{index}.")
        subtask_map[subtask_id].setdefault("tests", []).append(test)
        added[subtask_id] += 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Problem: {problem.get('id', '<unknown>')}")
    print(f"Seed: {args.seed}")
    print(f"Added: {sum(added.values())} test groups")
    for subtask_id, count in added.items():
        print(f"  {subtask_id}: +{count}")
    print(f"Output: {output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
