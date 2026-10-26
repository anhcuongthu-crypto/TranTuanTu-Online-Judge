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
