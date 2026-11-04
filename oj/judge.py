
import time
import base64
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


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

        
        payload = {
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

        if int(language_id) == 54:
            # Keep ASan/UBSan to detect out-of-bounds and undefined behavior,
            # but omit debug symbols: they increase compile time and are not
            # required for Judge0 to report Runtime Error.
            payload['compiler_options'] = (
                '-fsanitize=address,undefined '
                '-fno-omit-frame-pointer'
            )
            print("JUDGE COMPILER OPTIONS:",
      payload.get('compiler_options'), flush=True)

        return payload


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
                timeout=(3, 10)
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
                'Không kết nối được Judge0 khi gửi bài: '
                + str(exc)
            ) from exc

    def _get_submission(self, token):
        try:
            response = self.session.get(
                self.base_url + '/submissions/' + token,
                params={'base64_encoded': 'true'},
                headers=self._headers(),
                timeout=(3, 5)
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

    def _wait_for_submission(self, token, deadline=None):
        delay = 0.5
        errors = 0
        last_status = 'Unknown'

        while True:
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

            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)

        return {
            'status': last_status,
            'message': 'Đang chờ Judge0 trả kết quả.'
        }

    def run(self, source, language_id, stdin, expected,
            time_limit=1.0, memory_limit=256000):
        token = self._create_submission(
            source, language_id, stdin, expected,
            time_limit, memory_limit
        )

        return self._wait_for_submission(token)

    def _create_submissions_batch(self, payloads):
        try:
            response = self.session.post(
                self.base_url + '/submissions/batch',
                params={'base64_encoded': 'false'},
                json={'submissions': payloads},
                headers=self._headers(),
                timeout=(3, 15)
            )
        except requests.RequestException as exc:
            raise JudgeError(
                'Không kết nối được Judge0 khi gửi batch: ' + str(exc)
            ) from exc

        if response.status_code in (404, 405):
            return None

        if not response.ok:
            raise JudgeError(
                'Judge0 tạo batch thất bại: '
                + str(response.status_code) + ' '
                + self._get_error_text(response)
            )

        data = response.json()
        if isinstance(data, dict):
            data = data.get('submissions')

        if not isinstance(data, list) or len(data) != len(payloads):
            raise JudgeError('Judge0 trả về batch token không hợp lệ.')

        tokens = []
        for item in data:
            token = item.get('token') if isinstance(item, dict) else None
            if not token:
                raise JudgeError(
                    'Judge0 không tạo được một test trong batch: '
                    + str(item)[:500]
                )
            tokens.append(token)

        return tokens

    def _get_submissions_batch(self, tokens):
        try:
            response = self.session.get(
                self.base_url + '/submissions/batch',
                params={
                    'tokens': ','.join(tokens),
                    'base64_encoded': 'true'
                },
                headers=self._headers(),
                timeout=(3, 8)
            )
        except requests.RequestException as exc:
            raise JudgeError(
                'Không truy vấn được batch Judge0: ' + str(exc)
            ) from exc

        if response.status_code in (404, 405):
            return None

        if not response.ok:
            raise JudgeError(
                'Judge0 truy vấn batch thất bại: '
                + str(response.status_code) + ' '
                + self._get_error_text(response)
            )

        data = response.json()
        if isinstance(data, dict):
            data = data.get('submissions')

        if not isinstance(data, list):
            raise JudgeError('Judge0 trả về dữ liệu batch không hợp lệ.')

        return data

    def run_batch(self, source, language_id, tests,
                  time_limit=1.0, memory_limit=256000):
        if not tests:
            return []

        payloads = [
            self._payload(
                source,
                language_id,
                test['input'],
                test['output'],
                time_limit,
                memory_limit
            )
            for test in tests
        ]

        # Judge0 hỗ trợ tạo và truy vấn nhiều submission trong một HTTP
        # request. Chia lô tối đa 20 test để phù hợp giới hạn mặc định.
        tokens = []
        batch_create_supported = True
        for first in range(0, len(payloads), 20):
            chunk = payloads[first:first + 20]
            created = self._create_submissions_batch(chunk)

            if created is None:
                batch_create_supported = False
                break

            tokens.extend(created)

        # Tương thích với các Judge0 fork không bật Batch API.
        if not batch_create_supported:
            workers = min(8, len(tests))
            tokens = [None] * len(tests)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        self._create_submission,
                        source,
                        language_id,
                        test['input'],
                        test['output'],
                        time_limit,
                        memory_limit
                    ): i
                    for i, test in enumerate(tests)
                }
                for future in as_completed(futures):
                    tokens[futures[future]] = future.result()

        results = [None] * len(tokens)
        pending = set(range(len(tokens)))
        errors = [0] * len(tokens)
        delay = 0.3
        batch_get_supported = True

        while pending:
            # Poll theo từng nhóm <=20 token, thay vì một GET riêng cho
            # từng test ở mỗi vòng lặp.
            pending_list = sorted(pending)
            chunks = [
                pending_list[i:i + 20]
                for i in range(0, len(pending_list), 20)
            ]

            for chunk_indices in chunks:
                chunk_tokens = [tokens[i] for i in chunk_indices]

                if batch_get_supported:
                    try:
                        batch_data = self._get_submissions_batch(chunk_tokens)
                        if batch_data is None:
                            batch_get_supported = False
                            batch_data = None

                        if batch_data is not None:
                            by_token = {
                                item.get('token'): item
                                for item in batch_data
                                if isinstance(item, dict) and item.get('token')
                            }
                            ordered_data = [
                                by_token.get(token)
                                for token in chunk_tokens
                            ]

                            for i, data in zip(chunk_indices, ordered_data):
                                if data is None:
                                    errors[i] += 1
                                    if errors[i] >= 5:
                                        results[i] = {
                                            'status': 'Judge Unavailable',
                                            'message': 'Judge0 không trả kết quả cho test này.'
                                        }
                                        pending.discard(i)
                                    continue

                                result = self._format_result(data)
                                errors[i] = 0
                                status = result['status']
                                if status not in ('In Queue', 'Processing'):
                                    results[i] = result
                                    pending.discard(i)

                            continue

                    except JudgeError as exc:
                        for i in chunk_indices:
                            errors[i] += 1
                            if errors[i] >= 5:
                                results[i] = {
                                    'status': 'Judge Unavailable',
                                    'message': str(exc)
                                }
                                pending.discard(i)
                        continue

                # Fallback cho Judge0 không hỗ trợ GET batch.
                with ThreadPoolExecutor(
                    max_workers=min(8, len(chunk_indices))
                ) as executor:
                    futures = {
                        executor.submit(
                            self._get_submission,
                            tokens[i]
                        ): i
                        for i in chunk_indices
                        if i in pending
                    }
                    for future in as_completed(futures):
                        i = futures[future]
                        try:
                            result = future.result()
                            errors[i] = 0
                            if result['status'] not in ('In Queue', 'Processing'):
                                results[i] = result
                                pending.discard(i)
                        except JudgeError as exc:
                            errors[i] += 1
                            if errors[i] >= 5:
                                results[i] = {
                                    'status': 'Judge Unavailable',
                                    'message': str(exc)
                                }
                                pending.discard(i)

            if pending:
                time.sleep(delay)
                delay = min(delay * 1.4, 2.0)

        return results
