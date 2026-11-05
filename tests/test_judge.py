from unittest.mock import Mock, patch
import requests
from oj.judge import Judge0, JudgeError


def test_judge0_submits_and_polls_until_terminal_verdict():
    session = Mock()
    created = Mock()
    created.json.return_value = {'token': 'abc123'}
    created.raise_for_status.return_value = None
    polled = Mock()
    polled.json.return_value = {
        'status': {'description': 'Accepted'}, 'time': '0.01', 'memory': 1024,
        'stdout': '3\n', 'stderr': None, 'compile_output': None, 'message': None,
    }
    polled.raise_for_status.return_value = None
    session.post.return_value = created
    session.get.return_value = polled
    judge = Judge0('https://judge.example', 'secret', session=session)
    with patch('oj.judge.time.sleep'):
        result = judge.run('int main(){}', 54, '1 2\n', '3\n', 1, 256000)
    assert result['status'] == 'Accepted'
    assert session.post.call_args.kwargs['json']['cpu_time_limit'] == 1.0
    assert session.post.call_args.kwargs['headers']['X-Auth-Token'] == 'secret'
    assert session.get.call_count == 1


def test_judge0_network_error_becomes_actionable_judge_error():
    session = Mock()
    session.post.side_effect = requests.ConnectionError('network down')
    judge = Judge0('https://judge.example', session=session)
    try:
        judge.run('int main(){}', 54, '', '', 1, 256000)
    except JudgeError as exc:
        assert 'Không kết nối được Judge0' in str(exc)
    else:
        raise AssertionError('Expected JudgeError')



def test_judge0_run_batch_uses_batch_create_and_batch_poll():
    session = Mock()

    created = Mock()
    created.ok = True
    created.status_code = 201
    created.json.return_value = [
        {'token': 'token-1'},
        {'token': 'token-2'}
    ]

    polled = Mock()
    polled.ok = True
    polled.status_code = 200
    polled.json.return_value = {
        'submissions': [
            {
                'token': 'token-1',
                'status': {'description': 'Accepted'},
                'stdout': 'MQo=',
                'stderr': None,
                'compile_output': None,
                'message': None,
                'time': '0.01',
                'memory': 1024
            },
            {
                'token': 'token-2',
                'status': {'description': 'Wrong Answer'},
                'stdout': 'MAo=',
                'stderr': None,
                'compile_output': None,
                'message': None,
                'time': '0.01',
                'memory': 1024
            }
        ]
    }

    session.post.return_value = created
    session.get.return_value = polled

    judge = Judge0(
        'https://judge.example',
        session=session
    )

    tests = [
        {'input': '1\\n', 'output': '1\\n'},
        {'input': '2\\n', 'output': '2\\n'}
    ]

    with patch('oj.judge.time.sleep'):
        results = judge.run_batch(
            'int main(){}', 54, tests, 1, 256000
        )

    assert [item['status'] for item in results] == [
        'Accepted', 'Wrong Answer'
    ]
    assert session.post.call_count == 1
    assert session.post.call_args.args[0].endswith('/submissions/batch')
    assert len(session.post.call_args.kwargs['json']['submissions']) == 2
    assert session.get.call_count == 1
    assert session.get.call_args.args[0].endswith('/submissions/batch')
    assert session.get.call_args.kwargs['params']['tokens'] == 'token-1,token-2'


def test_single_submission_poll_has_a_hard_deadline():
    import time

    judge = Judge0("https://judge.example")
    judge._get_submission = lambda token: {"status": "Processing"}

    started = time.monotonic()
    result = judge._wait_for_submission(
        "token",
        deadline=started + 0.02
    )

    assert result["status"] == "Judge Timeout"
    assert time.monotonic() - started < 0.5


def test_partial_batch_creation_falls_back_only_for_missing_tests(monkeypatch):
    judge = Judge0("https://judge.example")
    individual_creates = []
    batch_calls = 0

    monkeypatch.setattr(
        judge,
        "_payload",
        lambda source, language_id, stdin, expected, time_limit, memory_limit:
            {"stdin": stdin, "expected_output": expected}
    )

    def create_batch(payloads):
        nonlocal batch_calls
        batch_calls += 1
        if batch_calls == 1:
            return [f"token-{i}" for i in range(len(payloads))]
        return None

    def create_one(source, language_id, stdin, expected, time_limit, memory_limit):
        individual_creates.append(stdin)
        return "token-last"

    def get_batch(tokens):
        return [
            {
                "token": token,
                "status": {"description": "Accepted"},
                "stdout": "",
                "stderr": "",
                "compile_output": "",
                "message": ""
            }
            for token in tokens
        ]

    monkeypatch.setattr(judge, "_create_submissions_batch", create_batch)
    monkeypatch.setattr(judge, "_create_submission", create_one)
    monkeypatch.setattr(judge, "_get_submissions_batch", get_batch)

    tests = [
        {"input": str(i), "output": str(i)}
        for i in range(21)
    ]
    results = judge.run_batch(
        "code",
        54,
        tests,
        max_wait_seconds=1
    )

    assert len(results) == 21
    assert all(result["status"] == "Accepted" for result in results)
    assert individual_creates == ["20"]
