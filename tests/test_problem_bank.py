"""Quality gates for the problem bank; intentionally fails on incomplete problems."""
import json
from pathlib import Path

BANK = Path(__file__).resolve().parents[1] / 'data' / 'problems.json'


def load_bank():
    return json.loads(BANK.read_text(encoding='utf-8'))


def test_problem_ids_and_titles_are_unique():
    problems = load_bank()
    assert problems
    assert len({p.get('id') for p in problems}) == len(problems)
    assert len({p.get('title') for p in problems}) == len(problems)


def test_every_problem_has_complete_statement_and_examples():
    problems = load_bank()
    required = ('statement', 'input_format', 'output_format', 'sample_input', 'sample_output', 'explanation')
    incomplete = [p.get('id', '?') for p in problems if any(not str(p.get(k, '')).strip() for k in required)]
    assert not incomplete, f'{len(incomplete)} problems missing required fields; first IDs: {incomplete[:20]}'


def test_subtasks_have_valid_scores_and_tests():
    problems = load_bank()
    invalid = []
    for p in problems:
        subtasks = p.get('subtasks') or []
        if not subtasks or sum(s.get('score', 0) for s in subtasks) != p.get('total_score'):
            invalid.append((p.get('id'), 'subtask score sum'))
            continue
        for s in subtasks:
            if not s.get('tests'):
                invalid.append((p.get('id'), f"subtask {s.get('id')} has no tests"))
                continue
            for i, t in enumerate(s['tests'], 1):
                if not isinstance(t.get('input'), str) or not isinstance(t.get('output'), str):
                    invalid.append((p.get('id'), f"subtask {s.get('id')} test {i} missing input/output"))
    assert not invalid, f'{len(invalid)} invalid problem/subtask records; first: {invalid[:20]}'


def test_all_problems_use_one_second_cpu_limit():
    problems = load_bank()
    invalid = [p.get('id') for p in problems if p.get('time_limit') != 1.0]
    assert not invalid, f'CPU time limit is not 1 second: {invalid[:20]}'
