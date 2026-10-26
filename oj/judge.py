
import time
import base64
import requests


class JudgeError(RuntimeError):
    pass


class Judge0:
    def __init__(self, base_url, api_key='', session=None):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = session or requests.Session()

    def _headers(self):
        headers = {'Content-Type': 'application/json'}

        if self.api_key:
            headers['X-Auth-Token'] = self.api_key

        return headers

    def _payload(self, source, language_id, stdin, expected,
                 time_limit, memory_limit):
        time_limit = max(0.1, float(time_limit))

        return {
            'source_code': source,
            'language_id': int(language_id),
            'stdin': stdin,
            'expected_output': expected,
            'cpu_time_limit': time_limit,
            'wall_time_limit': min(
                30.0, max(2.0, time_limit * 3)
            ),
            'memory_limit': int(memory_limit)
        }

    def _get_error_text(self, response):
        try:
            return response.text[:3000]
        except Exception:
            return 'Không đọc được nội dung lỗi từ Judge0.'

    def _decode_field(self, value):
        if value is None:
            return None

        if not isinstance(value, str):
            return value

        try:
            raw = base64.b64decode(value, validate=True)
            return raw.decode('utf-8', errors='replace')
        except (ValueError, UnicodeError):
            return value

    def _format_result(self, data):
        status_data = data.get('status') or {}
        status = status_data.get('description')

        if not status:
            status_names = {
                1: 'In Queue',
                2: 'Processing',
                3: 'Accepted',
                4: 'Wrong Answer',
                5: 'Time Limit Exceeded',
                6: 'Compilation Error',
                7: 'Runtime Error (SIGSEGV)',
                8: 'Runtime Error (SIGXFSZ)',
                9: 'Runtime Error (SIGFPE)',
                10: 'Runtime Error (SIGABRT)',
                11: 'Runtime Error (NZEC)',
                12: 'Runtime Error (Other)',
                13: 'Internal Error',
                14: 'Exec Format Error'
            }
            status = status_names.get(
                data.get('status_id'), 'Unknown'
            )

        return {
            'status': status,
            'time': data.get('time'),
            'memory': data.get('memory'),
            'stdout': self._decode_field(data.get('stdout')),
            'stderr': self._decode_field(data.get('stderr')),
            'compile_output': self._decode_field(
                data.get('compile_output')
            ),
            'message': self._decode_field(data.get('message'))
        }

    def _create_submission(self, source, language_id, stdin,
                           expected, time_limit, memory_limit):
        payload = self._payload(
            source, language_id, stdin, expected,
            time_limit, memory_limit
        )

        try:
            response = self.session.post(
                self.base_url + '/submissions',
                params={
                    'base64_encoded': 'false',
                    'wait': 'false'
                },
                json=payload,
                headers=self._headers(),
                timeout=(5, 20)
            )

            if not response.ok:
                raise JudgeError(
                    'Judge0 tạo submission thất bại: '
                    + str(response.status_code) + ' '
                    + self._get_error_text(response)
                )

            data = response.json()
            token = data.get('token')

            if not token:
                raise JudgeError(
                    'Judge0 không trả token: '
                    + str(data)[:1000]
                )

            return token

        except requests.RequestException as exc:
            raise JudgeError(
                'Không gửi được submission tới Judge0: '
                + str(exc)
            ) from exc

    def _get_submission(self, token):
        try:
            response = self.session.get(
                self.base_url + '/submissions/' + token,
                params={'base64_encoded': 'true'},
                headers=self._headers(),
                timeout=(5, 15)
            )

            if not response.ok:
                raise JudgeError(
                    'Judge0 truy vấn submission thất bại: '
                    + str(response.status_code) + ' '
                    + self._get_error_text(response)
                )

            return self._format_result(response.json())

        except requests.RequestException as exc:
            raise JudgeError(
                'Không truy vấn được kết quả Judge0: '
                + str(exc)
            ) from exc

    def _wait_for_submission(self, token, deadline):
        delay = 0.5
        errors = 0
        last_status = 'Unknown'

        while time.monotonic() < deadline:
            try:
                result = self._get_submission(token)
                errors = 0
                last_status = result['status']

                print(
                    'Judge0 status:', last_status,
                    flush=True
                )

                if last_status not in ('In Queue', 'Processing'):
                    return result

            except JudgeError as exc:
                errors += 1
                print('Judge0 poll error:', str(exc), flush=True)

                if errors >= 5:
                    return {
                        'status': 'Judge Unavailable',
                        'message': str(exc)
                    }

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                break

            time.sleep(min(delay, remaining))
            delay = min(delay * 1.5, 2.0)

        return {
            'status': 'Judge Timeout',
            'message': (
                'Hết thời gian chờ Judge0. '
                'Trạng thái cuối: ' + last_status
            )
        }

    def run(self, source, language_id, stdin, expected,
            time_limit=1.0, memory_limit=256000):
        token = self._create_submission(
            source, language_id, stdin, expected,
            time_limit, memory_limit
        )

        return self._wait_for_submission(
            token, time.monotonic() + 60
        )

    def run_batch(self, source, language_id, tests,
                  time_limit=1.0, memory_limit=256000):
        if not tests:
            return []

        tokens = []

        for test in tests:
            token = self._create_submission(
                source,
                language_id,
                test['input'],
                test['output'],
                time_limit,
                memory_limit
            )
            tokens.append(token)

        deadline = time.monotonic() + 60
        results = [None] * len(tokens)
        pending = set(range(len(tokens)))
        errors = [0] * len(tokens)
        delay = 0.5

        while pending and time.monotonic() < deadline:
            for i in list(pending):
                try:
                    result = self._get_submission(tokens[i])
                    errors[i] = 0
                    status = result['status']

                    print(
                        'Judge0 test', i + 1,
                        'status:', status,
                        flush=True
                    )

                    if status not in ('In Queue', 'Processing'):
                        results[i] = result
                        pending.remove(i)

                except JudgeError as exc:
                    errors[i] += 1
                    print(
                        'Judge0 test', i + 1,
                        'poll error:', str(exc),
                        flush=True
                    )

                    if errors[i] >= 5:
                        results[i] = {
                            'status': 'Judge Unavailable',
                            'message': str(exc)
                        }
                        pending.remove(i)

            if pending:
                remaining = deadline - time.monotonic()

                if remaining > 0:
                    time.sleep(min(delay, remaining))

                delay = min(delay * 1.5, 2.0)

        for i in pending:
            results[i] = {
                'status': 'Judge Timeout',
                'message': 'Hết thời gian chờ kết quả từ Judge0.'
            }

        return results
