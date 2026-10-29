
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from oj.database import connect
from oj.judge import Judge0, JudgeError


_pool = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()
_jobs = {}


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
    job_id = uuid.uuid4().hex

    with connect(app.config['DATABASE_PATH']) as db:
        cur = db.execute(
            '''INSERT INTO submissions
            (user_id, problem_id, language_id, source_code,
             verdict, score, max_score, details_json, contest_id)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)''',
            (
                user_id,
                problem['id'],
                language,
                code,
                'Queued',
                problem['total_score'],
                '[]',
                contest_id
            )
        )
        submission_id = cur.lastrowid

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

        with connect(app.config['DATABASE_PATH']) as db:
            db.execute(
                '''UPDATE submissions
                   SET verdict=?, details_json=?
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

        with _lock:
            if job_id in _jobs:
                _jobs[job_id]['status'] = 'Finished'

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
               SET verdict=?, score=?, details_json=?
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
    language
):
    started = time.perf_counter()

    with _lock:
        if job_id in _jobs:
            _jobs[job_id]['status'] = 'Processing'

    try:
        with connect(app.config['DATABASE_PATH']) as db:
            db.execute(
                '''UPDATE submissions
                   SET verdict=?
                   WHERE id=? AND user_id=?''',
                ('Processing', submission_id, user_id)
            )

        score = 0
        details = []
        statuses = []
        compile_error = False
        judge_error = False

        judge = Judge0(
            app.config['JUDGE0_URL'],
            app.config.get('JUDGE0_API_KEY', '')
        )

        subtasks = problem.get('subtasks', [])

        for st in subtasks:
            subtask_started = time.perf_counter()
            tests = st.get('tests', [])
            test_scores = _get_test_scores(st)

            batch_tests = [
                {
                    'input': test['input'],
                    'output': test['output']
                }
                for test in tests
            ]

            results = _run_batch_with_retry(
                judge,
                code,
                language,
                batch_tests,
                problem.get('time_limit', 1),
                problem.get('memory_limit', 256000)
            )

            sub_details = []
            subtask_score = 0

            for i, test in enumerate(tests):
                if i < len(results):
                    result = results[i] or {}
                else:
                    result = {
                        'status': 'Judge Unavailable',
                        'message': 'Judge0 không trả đủ kết quả.'
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

            # Dừng khi có lỗi biên dịch hoặc lỗi hệ thống chấm.
            if compile_error or judge_error:
                break

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
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]['status'] = 'Finished'


def _get_contest_id(app, submission_id, user_id):
    with connect(app.config['DATABASE_PATH']) as db:
        row = db.execute(
            '''SELECT contest_id
               FROM submissions
               WHERE id=? AND user_id=?''',
            (submission_id, user_id)
        ).fetchone()

    return row['contest_id'] if row else None
