"""Structural checks for hidden tests in the current problem bank.

The former statement-pattern reference solver was tied to an older bank and
reported false failures for every newer problem. Correct answers are verified
by the actual Judge0 submission path; this test checks test-data integrity.
"""
import json
from pathlib import Path

BANK = Path(__file__).resolve().parents[1] / 'data' / 'problems.json'


def test_hidden_test_cases_are_well_formed_and_nonempty():
    problems = json.loads(BANK.read_text(encoding='utf-8'))
    checked = 0

    for problem in problems:
        for subtask in problem.get('subtasks', []):
            tests = subtask.get('tests', [])
            assert tests, f"{problem.get('id')}: subtask {subtask.get('id')} has no tests"

            for index, case in enumerate(tests, 1):
                assert isinstance(case.get('input'), str), (
                    f"{problem.get('id')}: test {index} input must be text"
                )
                assert isinstance(case.get('output'), str), (
                    f"{problem.get('id')}: test {index} output must be text"
                )
                checked += 1

    assert checked > 0, "Problem bank has no hidden test cases"
