
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from oj.database import connect
from oj.judge import Judge0, JudgeError


_pool = ThreadPoolExecutor(max_workers=2)
# Bound running + waiting submissions so a burst cannot grow RAM without limit.
_MAX_PENDING_JOBS = 24
_capacity = threading.BoundedSemaphore(_MAX_PENDING_JOBS)


class QueueFullError(Exception):
    pass


_lock = threading.Lock()
_jobs = {}
_MAX_RETAINED_JOBS = 1000


def _mark_job_finished(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job['status'] = 'Finished'
            job['finished_at'] = time.monotonic()

        # Keep recent job IDs for polling, but discard old completed entries.
        if len(_jobs) > _MAX_RETAINED_JOBS:
            finished = sorted(
                (
                    (item.get('finished_at', 0.0), key)
                    for key, item in _jobs.items()
                    if item.get('status') == 'Finished'
                )
            )
            remove_count = max(0, len(_jobs) - 800)
            for _, key in finished[:remove_count]:
                _jobs.pop(key, None)


def _is_compile_error(status):
    return status in (
        'Compilation Error',
        'Compilation error',
        'Compile Error',
        'Error'
    )


def _is_judge_error(status):
    return status in (
        'Judge Unavailable',
        'Judge Timeout',
        'Internal Error',
        'Unknown'
    )



def _prepare_freopen_source(problem, code, language):
    """Require configured C++ freopen calls and map their files to Judge0 streams."""
    if not problem.get('use_freopen'):
        return code, None

    if int(language) != 54:
        return code, 'Bài này yêu cầu freopen và hiện chỉ hỗ trợ C++ (GNU G++).'

    input_file = str(problem.get('input_file', '')).strip()
    output_file = str(problem.get('output_file', '')).strip()
    if (
        not re.fullmatch(r'[A-Za-z0-9_-]+\.INP', input_file)
        or not re.fullmatch(r'[A-Za-z0-9_-]+\.OUT', output_file)
    ):
        return code, 'Cấu hình tên file freopen của bài không hợp lệ.'

    def replace_call(source, filename, mode, stream, target):
        pattern = re.compile(
            r'freopen\s*\(\s*([\"\'])'
            + re.escape(filename)
            + r'\1\s*,\s*([\"\'])'
            + re.escape(mode)
            + r'\2\s*,\s*'
            + re.escape(stream)
            + r'\s*\)'
        )
        return pattern.sub(
            lambda match: match.group(0).replace(filename, target),
            source
        ), bool(pattern.search(source))

    transformed, has_input = replace_call(
        code, input_file, 'r', 'stdin', '/dev/stdin'
    )
    transformed, has_output = replace_call(
        transformed, output_file, 'w', 'stdout', '/dev/stdout'
    )

    if not has_input or not has_output:
        missing = []
        if not has_input:
            missing.append(f'freopen("{input_file}", "r", stdin)')
        if not has_output:
            missing.append(f'freopen("{output_file}", "w", stdout)')
        return code, 'Thiếu lệnh bắt buộc: ' + ' và '.join(missing)

    return transformed, None


def _get_test_scores(st):
    tests = st.get('tests', [])
    n = len(tests)

    if n == 0:
        return []

    if all('score' in test for test in tests):
        return [float(test['score']) for test in tests]

    total = float(st.get('score', 0))
    base = total / n

    return [base for _ in range(n)]


def _run_batch_with_retry(
    judge,
    code,
    language,
    batch_tests,
    time_limit,
    memory_limit,
    max_attempts=3
):
    """
    Thử lại khi Judge0 gặp lỗi tạm thời.
    Không tự chuyển lỗi của hệ thống chấm thành Wrong Answer.
    """
    last_results = []

    for attempt in range(max_attempts):
        try:
            results = judge.run_batch(
                code,
                language,
                batch_tests,
                time_limit,
                memory_limit
            )

            if not isinstance(results, list):
                results = []

            last_results = results

            has_temporary_error = (
                len(results) != len(batch_tests)
                or any(
                    _is_judge_error(
                        (item or {}).get('status', 'Unknown')
                    )
                    for item in results
                )
            )

            if not has_temporary_error:
                return results

            print(
                f'[OJ RETRY] Judge0 returned temporary error; '
                f'attempt={attempt + 1}/{max_attempts}',
                flush=True
            )

        except Exception as exc:
            print(
                f'[OJ RETRY] Judge0 exception; '
                f'attempt={attempt + 1}/{max_attempts}: {exc}',
                flush=True
            )

        if attempt < max_attempts - 1:
            time.sleep(attempt + 1)

    # Nếu kết quả cuối cùng vẫn thiếu, tạo trạng thái lỗi
    # cho những test chưa có kết quả.
    if len(last_results) < len(batch_tests):
        last_results = list(last_results)

        while len(last_results) < len(batch_tests):
            last_results.append({
                'status': 'Judge Unavailable',
                'message': (
                    'Judge0 không trả đủ kết quả sau nhiều lần thử.'
                )
            })

    return last_results


def enqueue(app, user_id, problem, code, language, contest_id=None):
    # Reject overload before writing a submission row. This bounds both the
    # executor's pending work and the source-code objects retained in memory.
    if not _capacity.acquire(blocking=False):
        raise QueueFullError('Hàng đợi chấm bài đang đầy. Vui lòng thử lại sau.')

    job_id = uuid.uuid4().hex

    try:
        with connect(app.config['DATABASE_PATH']) as db:
            cur = db.execute(
                '''INSERT INTO submissions
                (user_id, problem_id, language_id, source_code,
                 verdict, score, max_score, details_json, contest_id,
                 problem_json)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?)''',
                (
                    user_id,
                    problem['id'],
                    language,
                    code,
                    'Queued',
                    problem['total_score'],
                    '[]',
                    contest_id,
                    json.dumps(problem, ensure_ascii=False)
                )
            )
            submission_id = cur.lastrowid
    except Exception:
        _capacity.release()
        raise

    with _lock:
        _jobs[job_id] = {
            'status': 'Queued',
            'submission_id': submission_id
        }

    try:
        _pool.submit(
            _run_job,
            app,
            job_id,
            submission_id,
            user_id,
            problem,
            code,
            language
        )

    except Exception as exc:
        message = 'Không thể khởi chạy worker: ' + str(exc)

        try:
            with connect(app.config['DATABASE_PATH']) as db:
                db.execute(
                    '''UPDATE submissions
                       SET verdict=?, details_json=?, problem_json=NULL
                       WHERE id=? AND user_id=?''',
                    (
                        'Judge Unavailable',
                        json.dumps([{
                            'status': 'Judge Unavailable',
                            'message': message[:1000]
                        }], ensure_ascii=False),
                        submission_id,
                        user_id
                    )
                )
        finally:
            _mark_job_finished(job_id)
            _capacity.release()

        print(
            f'[OJ ERROR] Cannot start submission={submission_id}: {exc}',
            flush=True
        )

    return job_id, submission_id


def get_job(app, job_id, user_id):
    with _lock:
        job = _jobs.get(job_id)

    if not job:
        return None

    with connect(app.config['DATABASE_PATH']) as db:
        row = db.execute(
            '''SELECT id, problem_id, verdict, score, max_score,
                      details_json, created_at, contest_id
               FROM submissions
               WHERE id=? AND user_id=?''',
            (job['submission_id'], user_id)
        ).fetchone()

    if not row:
        return None

    result = dict(row)

    try:
        result['details'] = json.loads(
            result.pop('details_json') or '[]'
        )
    except (TypeError, ValueError):
        result['details'] = []

    result['status'] = result.get('verdict', job['status'])

    return result


def _save_result(
    app,
    submission_id,
    user_id,
    problem,
    verdict,
    score,
    details
):
    with connect(app.config['DATABASE_PATH']) as db:
        db.execute(
            '''UPDATE submissions
               SET verdict=?, score=?, details_json=?, problem_json=NULL
               WHERE id=? AND user_id=?''',
            (
                verdict,
                score,
                json.dumps(details, ensure_ascii=False),
                submission_id,
                user_id
            )
        )

        row = db.execute(
            '''SELECT contest_id
               FROM submissions
               WHERE id=? AND user_id=?''',
            (submission_id, user_id)
        ).fetchone()

        contest_id = row['contest_id'] if row else None

        # Chỉ cập nhật bảng solves cho bài ngoài contest.
        if row and contest_id is None:
            db.execute(
                '''INSERT INTO solves
                   (user_id, problem_id, best_score)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, problem_id)
                   DO UPDATE SET best_score =
                       CASE
                           WHEN solves.best_score > excluded.best_score
                           THEN solves.best_score
                           ELSE excluded.best_score
                       END''',
                (user_id, problem['id'], score)
            )


def _run_job(
    app,
    job_id,
    submission_id,
    user_id,
    problem,
    code,
    language,
    expected_status='Queued'
):
    started = time.perf_counter()

    try:
        # Atomic claim: a worker only starts a job from the state it owns.
        # This prevents a stale in-memory task from running after recovery.
        with connect(app.config['DATABASE_PATH']) as db:
            claimed_count = db.execute(
                '''UPDATE submissions
                   SET verdict=?
                   WHERE id=? AND user_id=? AND verdict=?''',
                ('Processing', submission_id, user_id, expected_status)
            ).rowcount

        if claimed_count != 1:
            print(
                f'[OJ QUEUE] Skip duplicate/stale worker '
                f'submission={submission_id}',
                flush=True
            )
            return

        with _lock:
            if job_id in _jobs:
                _jobs[job_id]['status'] = 'Processing'

        score = 0
        details = []
        statuses = []
        compile_error = False
        judge_error = False

        judge = Judge0(
            app.config['JUDGE0_URL'],
            app.config.get('JUDGE0_API_KEY', '')
        )

        code_to_run, freopen_error = _prepare_freopen_source(
            problem, code, language
        )

        subtasks = problem.get('subtasks', [])

        # Gửi test của tất cả subtasks trong cùng một batch để tránh
        # phải chờ tuần tự từng subtask.
        flat_tests = []
        subtask_ranges = []
        for st in subtasks:
            tests = st.get('tests', [])
            scores = _get_test_scores(st)
            first = len(flat_tests)

            for test in tests:
                flat_tests.append({
                    'input': test['input'],
                    'output': test['output']
                })

            subtask_ranges.append((st, first, len(flat_tests), scores))

        batch_started = time.perf_counter()
        if freopen_error:
            results = [
                {
                    'status': 'Wrong Answer',
                    'message': freopen_error
                }
                for _ in flat_tests
            ]
        else:
            results = _run_batch_with_retry(
                judge,
                code_to_run,
                language,
                flat_tests,
                problem.get('time_limit', 1),
                problem.get('memory_limit', 256000),
                max_attempts=1
            )

        for st, first, last, test_scores in subtask_ranges:
            subtask_started = time.perf_counter()
            tests = st.get('tests', [])
            sub_details = []
            subtask_score = 0

            for i, test in enumerate(tests):
                result_index = first + i
                if result_index < len(results):
                    result = results[result_index] or {}
                else:
                    result = {
                        'status': 'Judge Timeout',
                        'message': 'Hết thời gian chờ kết quả từ Judge0.'
                    }

                status = result.get('status', 'Unknown')
                statuses.append(status)

                max_test_score = test_scores[i]
                if status == 'Accepted':
                    earned = max_test_score
                    subtask_score += earned
                else:
                    earned = 0

                if _is_compile_error(status):
                    compile_error = True
                if _is_judge_error(status):
                    judge_error = True

                message = (
                    result.get('compile_output')
                    or result.get('stderr')
                    or result.get('message')
                    or ''
                )

                sub_details.append({
                    'test': i + 1,
                    'status': status,
                    'score': earned,
                    'max_score': max_test_score,
                    'time': result.get('time'),
                    'memory': result.get('memory'),
                    'message': str(message)[:1000]
                })

            score += subtask_score
            details.append({
                'subtask': st.get('id'),
                'name': st.get('name', ''),
                'score': subtask_score,
                'max_score': sum(test_scores),
                'tests': sub_details
            })

            print(
                f'[OJ SPEED] problem={problem["id"]} '
                f'subtask={st.get("id")} tests={len(tests)} '
                f'elapsed={time.perf_counter() - subtask_started:.2f}s',
                flush=True
            )

        print(
            f'[OJ SPEED] submission={submission_id} '
            f'batch_tests={len(flat_tests)} '
            f'batch_elapsed={time.perf_counter() - batch_started:.2f}s',
            flush=True
        )

        total_score = float(problem['total_score'])

        if compile_error:
            verdict = 'Error'
            score = 0

        elif judge_error:
            verdict = 'Judge Unavailable'

        elif score >= total_score:
            verdict = 'Accepted'
            score = total_score

        elif score > 0:
            verdict = 'Partially Accepted'

        elif 'Wrong Answer' in statuses:
            verdict = 'Wrong Answer'

        elif 'Time Limit Exceeded' in statuses:
            verdict = 'Time Limit Exceeded'

        elif 'Memory Limit Exceeded' in statuses:
            verdict = 'Memory Limit Exceeded'

        elif any(
            isinstance(s, str) and s.startswith('Runtime Error')
            for s in statuses
        ):
            verdict = 'Runtime Error'

        else:
            verdict = 'Wrong Answer'

        total_elapsed = time.perf_counter() - started

        print(
            f'[OJ SPEED] submission={submission_id} '
            f'verdict={verdict} score={score}/'
            f'{problem["total_score"]} total={total_elapsed:.2f}s',
            flush=True
        )

        _save_result(
            app,
            submission_id,
            user_id,
            problem,
            verdict,
            score,
            details
        )

    except Exception as exc:
        print(
            f'[OJ ERROR] submission={submission_id}: {exc}',
            flush=True
        )

        error_details = [{
            'status': 'Judge Unavailable',
            'score': 0,
            'message': str(exc)[:1000]
        }]

        try:
            _save_result(
                app,
                submission_id,
                user_id,
                problem,
                'Judge Unavailable',
                0,
                error_details
            )

        except Exception as save_exc:
            print(
                f'[OJ ERROR] Cannot save failure '
                f'submission={submission_id}: {save_exc}',
                flush=True
            )

    finally:
        _mark_job_finished(job_id)
        _capacity.release()
        try:
            _dispatch_next_queued(app)
        except Exception as dispatch_exc:
            print(
                f'[OJ QUEUE] Could not dispatch next job: {dispatch_exc}',
                flush=True
            )


def _mark_recovery_failure(app, submission_id, user_id, message):
    with connect(app.config['DATABASE_PATH']) as db:
        db.execute(
            '''UPDATE submissions
               SET verdict=?, score=0, details_json=?, problem_json=NULL
               WHERE id=? AND user_id=? AND verdict IN ('Queued', 'Starting')''',
            (
                'Judge Unavailable',
                json.dumps([{
                    'status': 'Judge Unavailable',
                    'score': 0,
                    'message': message[:1000]
                }], ensure_ascii=False),
                submission_id,
                user_id
            )
        )


def _dispatch_next_queued(app):
    """Move one durable Queued row into the bounded in-memory executor."""
    while _capacity.acquire(blocking=False):
        try:
            with connect(app.config['DATABASE_PATH']) as db:
                row = db.execute(
                    '''SELECT id, user_id, language_id, source_code,
                              problem_json
                       FROM submissions
                       WHERE verdict='Queued'
                       ORDER BY id ASC
                       LIMIT 1'''
                ).fetchone()

                if not row:
                    _capacity.release()
                    return False

                try:
                    problem = json.loads(row['problem_json'] or '')
                    if not isinstance(problem, dict) or not problem.get('id'):
                        raise ValueError('Thiếu bản chụp đề bài.')
                except (TypeError, ValueError) as exc:
                    db.execute(
                        '''UPDATE submissions
                           SET verdict=?, score=0, details_json=?, problem_json=NULL
                           WHERE id=? AND verdict='Queued' ''',
                        (
                            'Judge Unavailable',
                            json.dumps([{
                                'status': 'Judge Unavailable',
                                'score': 0,
                                'message': (
                                    'Không thể khôi phục bài chờ sau khi máy chủ '
                                    'khởi động lại: ' + str(exc)
                                )[:1000]
                            }], ensure_ascii=False),
                            row['id']
                        )
                    )
                    should_skip = True
                    claimed = None
                else:
                    should_skip = False
                    claimed_count = db.execute(
                        '''UPDATE submissions
                           SET verdict='Starting'
                           WHERE id=? AND verdict='Queued' ''',
                        (row['id'],)
                    ).rowcount

            if should_skip:
                _capacity.release()
                continue

            if claimed_count != 1:
                _capacity.release()
                continue

            job_id = uuid.uuid4().hex
            submission_id = row['id']
            user_id = row['user_id']

            with _lock:
                _jobs[job_id] = {
                    'status': 'Starting',
                    'submission_id': submission_id
                }

            try:
                _pool.submit(
                    _run_job,
                    app,
                    job_id,
                    submission_id,
                    user_id,
                    problem,
                    row['source_code'],
                    row['language_id'],
                    'Starting'
                )
                return True
            except Exception as exc:
                _mark_recovery_failure(
                    app,
                    submission_id,
                    user_id,
                    'Không thể khởi động worker sau khi khôi phục: ' + str(exc)
                )
                _mark_job_finished(job_id)
                _capacity.release()
                print(
                    f'[OJ ERROR] Cannot recover submission={submission_id}: {exc}',
                    flush=True
                )
        except Exception:
            _capacity.release()
            raise

    return False

def recover_pending(app):
    """Recover safely queued jobs and close ambiguous interrupted jobs.

    A row left at Processing may already have been sent to Judge0. It is
    therefore not replayed automatically, which avoids duplicate judging.
    """
    marker = '_trantu_queue_recovered'
    if app.extensions.get(marker):
        return 0

    # Starting means the worker had not claimed Processing yet; it is safe
    # to put the row back into Queued before dispatching it again.
    with connect(app.config['DATABASE_PATH']) as db:
        db.execute(
            "UPDATE submissions SET verdict='Queued' WHERE verdict='Starting'"
        )

        interrupted = db.execute(
            '''SELECT id, user_id
               FROM submissions
               WHERE verdict='Processing'
               ORDER BY id ASC'''
        ).fetchall()

        for row in interrupted:
            db.execute(
                '''UPDATE submissions
                   SET verdict=?, score=0, details_json=?, problem_json=NULL
                   WHERE id=? AND user_id=? AND verdict='Processing' ''',
                (
                    'Judge Unavailable',
                    json.dumps([{
                        'status': 'Judge Unavailable',
                        'score': 0,
                        'message': (
                            'Máy chủ đã khởi động lại khi bài đang được chấm. '
                            'Bài không được tự gửi lại để tránh chấm trùng; '
                            'vui lòng nộp lại.'
                        )
                    }], ensure_ascii=False),
                    row['id'],
                    row['user_id']
                )
            )

    app.extensions[marker] = True
    restored = 0
    while _dispatch_next_queued(app):
        restored += 1

    if restored or interrupted:
        app.logger.info(
            '[OJ QUEUE] Startup recovery: restored=%s interrupted=%s',
            restored,
            len(interrupted)
        )
    return restored


def _get_contest_id(app, submission_id, user_id):
    with connect(app.config['DATABASE_PATH']) as db:
        row = db.execute(
            '''SELECT contest_id
               FROM submissions
               WHERE id=? AND user_id=?''',
            (submission_id, user_id)
        ).fetchone()

    return row['contest_id'] if row else None
