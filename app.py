import base64
import json
import os
import re
import shutil
import urllib.request
import urllib.error
from urllib.parse import quote
from datetime import datetime
from pathlib import Path

from flask import (
    Flask, jsonify, request, render_template,
    session, redirect, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash

from oj.database import (
    connect, init_db, is_postgres_path, DB_INTEGRITY_ERRORS
)
from oj.job_queue import enqueue
from oj.admin import register_admin_routes
from oj.history import (
    initialize_history,
    save_history,
    get_history,
    get_history_detail,
    restore_history_data,
    remove_duplicates,
)


# =========================================================
# PHẦN 1: NGÂN HÀNG ĐỀ, GITHUB, KHỞI TẠO ỨNG DỤNG
# =========================================================

def load_problems(path):
    path = Path(path)

    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding='utf-8'))

    if not isinstance(data, list):
        raise ValueError('Problems JSON phải là danh sách.')

    ids = set()

    for p in data:
        pid = str(p.get('id', '')).strip()

        if not pid:
            raise ValueError('Có bài tập thiếu ID.')

        if pid in ids:
            raise ValueError('Trùng problem ID: ' + pid)

        ids.add(pid)

        if not isinstance(p.get('subtasks'), list):
            raise ValueError('Subtasks không hợp lệ: ' + pid)

        if not p['subtasks']:
            raise ValueError('Bài không có subtask: ' + pid)

        total = float(p.get('total_score', 0))
        subtask_total = sum(
            float(s.get('score', 0))
            for s in p['subtasks']
        )

        if abs(total - subtask_total) > 1e-9:
            raise ValueError(
                'Điểm subtasks không khớp bài ' + pid
            )

        for s in p['subtasks']:
            if not isinstance(s.get('tests'), list) or not s['tests']:
                raise ValueError(
                    'Subtask thiếu test ở bài ' + pid
                )

    return data


def github_request(path, method='GET', payload=None):
    token = os.getenv('GITHUB_TOKEN')
    owner = os.getenv('GITHUB_OWNER')
    repo = os.getenv('GITHUB_REPO')

    if not token or not owner or not repo:
        raise RuntimeError(
            'Thiếu GITHUB_TOKEN, GITHUB_OWNER hoặc GITHUB_REPO.'
        )

    url = (
        f'https://api.github.com/repos/'
        f'{owner}/{repo}{path}'
    )

    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'Tran-Tu-36-Online-Judge'
    }

    body = None

    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else {}

    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(
            f'GitHub API lỗi {e.code}: {detail}'
        )


def github_read_problems():
    branch = quote(
        os.getenv('GITHUB_BRANCH', 'main'),
        safe=''
    )

    result = github_request(
        '/contents/data/problems.json?ref=' + branch
    )

    content = result.get('content', '')

    if not content:
        raise RuntimeError(
            'GitHub không trả về nội dung problems.json.'
        )

    data = json.loads(
        base64.b64decode(content).decode('utf-8')
    )

    if not isinstance(data, list):
        raise ValueError(
            'Problems JSON trên GitHub phải là danh sách.'
        )

    return data, result['sha']


def save_problems(data, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(data, list):
        raise ValueError(
            'Ngân hàng đề phải là danh sách.'
        )

    ids = [str(p.get('id', '')).strip() for p in data]

    if any(not pid for pid in ids):
        raise ValueError('Có bài tập thiếu ID.')

    if len(ids) != len(set(ids)):
        raise ValueError('Có ID bài tập bị trùng.')

    content = json.dumps(
        data,
        ensure_ascii=False,
        indent=2
    )

    # Nếu cấu hình GitHub, lưu lên GitHub trước.
    if os.getenv('GITHUB_TOKEN'):
        branch = os.getenv('GITHUB_BRANCH', 'main')

        if not os.getenv('GITHUB_OWNER') or not os.getenv('GITHUB_REPO'):
            raise RuntimeError(
                'Thiếu GITHUB_OWNER hoặc GITHUB_REPO.'
            )

        _, sha = github_read_problems()

        payload = {
            'message': 'Update problem bank from TranTu Online Judge',
            'content': base64.b64encode(
                content.encode('utf-8')
            ).decode('ascii'),
            'sha': sha,
            'branch': branch
        }

        github_request(
            '/contents/data/problems.json',
            method='PUT',
            payload=payload
        )

        saved_data, _ = github_read_problems()

        if saved_data != data:
            raise RuntimeError(
                'Dữ liệu trên GitHub chưa khớp với dữ liệu cần lưu.'
            )

    # Sau khi GitHub lưu thành công mới ghi file cục bộ.
    tmp = target.with_suffix(target.suffix + '.tmp')

    try:
        tmp.write_text(content, encoding='utf-8')
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()


def validate_problem(p):
    if not p.get('id'):
        raise ValueError('Bài tập thiếu ID.')

    if not p.get('title') or not p.get('statement'):
        raise ValueError('Thiếu tiêu đề hoặc đề bài.')

    subtasks = p.get('subtasks')

    if not isinstance(subtasks, list) or not subtasks:
        raise ValueError('Bài phải có ít nhất một subtask.')

    total = float(p.get('total_score', 0))

    if total <= 0:
        raise ValueError('total_score phải dương.')

    score_sum = 0

    for s in subtasks:
        if not isinstance(s, dict):
            raise ValueError('Subtask không hợp lệ.')

        score = float(s.get('score', 0))

        if score <= 0:
            raise ValueError('Điểm subtask phải dương.')

        tests = s.get('tests')

        if not isinstance(tests, list) or not tests:
            raise ValueError('Mỗi subtask cần ít nhất một test.')

        score_sum += score

    if abs(score_sum - total) > 1e-9:
        raise ValueError(
            'Tổng điểm subtasks phải bằng total_score.'
        )


def initialize_problem_file(app):
    target = Path(app.config['PROBLEMS_PATH'])
    target.parent.mkdir(parents=True, exist_ok=True)

    # Không ghi đè dữ liệu đã có trên persistent disk.
    if target.exists():
        return

    source = Path(__file__).parent / 'data' / 'problems.json'

    if source.exists() and source.resolve() != target.resolve():
        shutil.copy2(source, target)
    elif not target.exists():
        target.write_text('[]', encoding='utf-8')


# =========================================================
# KHỞI TẠO FLASK
# =========================================================

def create_app(test_config=None):
    app = Flask(
        __name__,
        instance_relative_config=True
    )

    app.config.from_mapping(
        SECRET_KEY=os.getenv(
            'SECRET_KEY',
            'dev-change-me'
        ),
        DATABASE_PATH=os.getenv(
            'DATABASE_URL'
        ) or os.getenv(
            'DATABASE_PATH',
            str(Path(app.instance_path) / 'online_judge.sqlite3')
        ),
        PROBLEMS_PATH=os.getenv(
            'PROBLEMS_PATH',
            str(Path(__file__).parent / 'data' / 'problems.json')
        ),
        JUDGE0_URL=os.getenv(
            'JUDGE0_URL',
            'https://ce.judge0.com'
        ),
        JUDGE0_API_KEY=os.getenv(
            'JUDGE0_API_KEY',
            ''
        ),
        ADMIN_USERNAME=os.getenv(
            'ADMIN_USERNAME',
            'admin'
        ),
        ADMIN_PASSWORD=os.getenv(
            'ADMIN_PASSWORD',
            ''
        ),
        TESTING=False
    )

    if test_config:
        app.config.update(test_config)

    db_path = app.config['DATABASE_PATH']

    if not is_postgres_path(db_path):
        Path(db_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

    initialize_problem_file(app)

    app.logger.info(
        'Database backend: %s',
        'PostgreSQL'
        if is_postgres_path(db_path)
        else 'SQLite'
    )

    init_db(db_path)
    initialize_history(db_path)

    # Tạo hoặc nâng quyền tài khoản admin chính.
    if app.config.get('ADMIN_PASSWORD'):
        with connect(db_path) as db:
            row = db.execute(
                'SELECT id FROM users WHERE username=?',
                (app.config['ADMIN_USERNAME'],)
            ).fetchone()

            if row:
                db.execute(
                    '''UPDATE users
                       SET is_admin=1, approved=1
                       WHERE id=?''',
                    (row['id'],)
                )
            else:
                db.execute(
                    '''INSERT INTO users
                       (username, password_hash, is_admin, approved)
                       VALUES (?, ?, 1, 1)''',
                    (
                        app.config['ADMIN_USERNAME'],
                        generate_password_hash(
                            app.config['ADMIN_PASSWORD']
                        )
                    )
                )

    # Tạo hoặc nâng quyền admin thứ hai nếu có cấu hình.
    admin2_username = os.getenv(
        'ADMIN2_USERNAME',
        ''
    ).strip()

    admin2_password = os.getenv(
        'ADMIN2_PASSWORD',
        ''
    )

    if admin2_username and admin2_password:
        with connect(db_path) as db:
            row = db.execute(
                'SELECT id FROM users WHERE username=?',
                (admin2_username,)
            ).fetchone()

            if row:
                db.execute(
                    '''UPDATE users
                       SET is_admin=1, approved=1
                       WHERE id=?''',
                    (row['id'],)
                )
            else:
                db.execute(
                    '''INSERT INTO users
                       (username, password_hash, is_admin, approved)
                       VALUES (?, ?, 1, 1)''',
                    (
                        admin2_username,
                        generate_password_hash(admin2_password)
                    )
                )

    # Cache ngân hàng đề trong bộ nhớ.
    problems_cache = None

    def problems(refresh=False):
        nonlocal problems_cache

        if problems_cache is not None and not refresh:
            return problems_cache

        if os.getenv('GITHUB_TOKEN'):
            data, _ = github_read_problems()
        else:
            data = load_problems(
                app.config['PROBLEMS_PATH']
            )

        problems_cache = data
        return problems_cache

    def update_problems_cache(data):
        nonlocal problems_cache
        problems_cache = data

    def current_user():
        uid = session.get('user_id')

        if not uid:
            return None

        with connect(db_path) as db:
            row = db.execute(
                '''SELECT id, username, is_admin, approved
                   FROM users WHERE id=?''',
                (uid,)
            ).fetchone()

        return dict(row) if row else None

    def admin_required():
        user = current_user()

        if user and user['is_admin']:
            return user

        return None

    def parse_contest_time(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                'Thiếu thời gian bắt đầu hoặc kết thúc.'
            )

        try:
            result = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ValueError('Thời gian không hợp lệ.')

        if result.tzinfo is not None:
            raise ValueError(
                'Hãy nhập thời gian địa phương, không kèm múi giờ.'
            )

        return result

    def contest_state(contest):
        now = datetime.now()
        start = parse_contest_time(contest['start_time'])
        end = parse_contest_time(contest['end_time'])

        if now < start:
            return 'upcoming'

        if now >= end:
            return 'ended'

        return 'running'

    def get_contest_data(contest_id, allow_hidden=False):
        with connect(db_path) as db:
            contest = db.execute(
                'SELECT * FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()

            if not contest:
                return None

            if not contest['is_visible'] and not allow_hidden:
                return None

            ids = db.execute(
                '''SELECT problem_id, total_score
                   FROM contest_problems
                   WHERE contest_id=?
                   ORDER BY position, problem_id''',
                (contest_id,)
            ).fetchall()

            custom_rows = db.execute(
                '''SELECT problem_id, title, statement,
                          input_desc, output_desc, total_score,
                          sample_input, sample_output
                   FROM contest_custom_problems
                   WHERE contest_id=?''',
                (contest_id,)
            ).fetchall()

        item = dict(contest)
        item['is_visible'] = bool(item['is_visible'])
        item['problem_ids'] = [
            r['problem_id'] for r in ids
        ]

        bank = {
            str(p['id']): p
            for p in problems()
        }

        custom = {
            str(p['problem_id']): dict(p)
            for p in custom_rows
        }

        item['problems'] = []

        for row in ids:
            pid = str(row['problem_id'])

            if pid in custom:
                p = custom[pid]

                item['problems'].append({
                    'id': pid,
                    'title': p['title'],
                    'total_score': p['total_score'],
                    'is_custom': True,
                    'statement': p['statement'],
                    'input_desc': p['input_desc'],
                    'output_desc': p['output_desc'],
                    'sample_input': p['sample_input'] or '',
                    'sample_output': p['sample_output'] or ''
                })

            elif pid in bank:
                p = bank[pid]

                item['problems'].append({
                    'id': pid,
                    'title': p.get('title', pid),
                    'total_score': row['total_score'],
                    'is_custom': False,
                    'statement': p.get('statement', ''),
                    'input_desc': p.get('input_desc', ''),
                    'output_desc': p.get('output_desc', ''),
                    'sample_input': p.get('sample_input', ''),
                    'sample_output': p.get('sample_output', '')
                })

        item['state'] = contest_state(item)
        return item
    # =====================================================
    # PHẦN 2: TRANG WEB, TÀI KHOẢN, HỒ SƠ VÀ BÀI TẬP
    # =====================================================

    @app.get('/health')
    def health():
        try:
            return jsonify(
                ok=True,
                problem_count=len(problems())
            )
        except Exception as e:
            app.logger.exception('Health check thất bại')
            return jsonify(
                ok=False,
                error=str(e)
            ), 500

    @app.get('/')
    def home():
        return render_template('index.html')

    @app.get('/problems/<pid>')
    def problem_page(pid):
        p = next(
            (x for x in problems() if str(x['id']) == pid),
            None
        )

        if p:
            return render_template(
                'problem.html',
                problem=p
            )

        return render_template('not_found.html'), 404

    @app.get('/problems/<pid>/submit')
    def submit_problem_page(pid):
        p = next(
            (x for x in problems() if str(x['id']) == pid),
            None
        )

        if p:
            return render_template(
                'submit_problem.html',
                problem=p
            )

        return render_template('not_found.html'), 404

    # --------------------- API BÀI TẬP ---------------------

    @app.get('/api/problems')
    def api_problems():
        return jsonify([
            {
                'id': p['id'],
                'title': p.get('title', ''),
                'category': p.get('category', ''),
                'difficulty': p.get('difficulty', ''),
                'total_score': p.get('total_score', 0)
            }
            for p in problems()
        ])

    @app.get('/api/problems/<pid>')
    def api_problem(pid):
        p = next(
            (x for x in problems() if str(x['id']) == pid),
            None
        )

        if not p:
            return jsonify(
                error='Không tìm thấy bài.'
            ), 404

        # Chỉ trả thông tin đề và subtasks công khai.
        # Không trả test ẩn cho trình duyệt.
        public = {
            'id': p['id'],
            'title': p.get('title', ''),
            'category': p.get('category', ''),
            'difficulty': p.get('difficulty', ''),
            'statement': p.get('statement', ''),
            'input_desc': p.get('input_desc', ''),
            'output_desc': p.get('output_desc', ''),
            'sample_input': p.get('sample_input', ''),
            'sample_output': p.get('sample_output', ''),
            'total_score': p.get('total_score', 0),
            'time_limit': p.get('time_limit', 1),
            'memory_limit': p.get('memory_limit', 256000),
            'subtasks': [
                {
                    'id': s.get('id'),
                    'name': s.get('name', ''),
                    'score': s.get('score', 0)
                }
                for s in p.get('subtasks', [])
            ]
        }

        return jsonify(public)

    # ---------------------- ĐĂNG KÝ ------------------------

    @app.post('/api/register')
    def register():
        d = request.get_json(silent=True) or {}

        username = str(
            d.get('username', '')
        ).strip()

        password = str(
            d.get('password', '')
        )

        if not re.fullmatch(
            r'[A-Za-z0-9_]{3,24}',
            username
        ):
            return jsonify(
                error=(
                    'Tên đăng nhập dài 3-24 ký tự, '
                    'chỉ gồm chữ, số và dấu _.'
                )
            ), 400

        if len(password) < 8:
            return jsonify(
                error='Mật khẩu tối thiểu 8 ký tự.'
            ), 400

        reserved = {
            app.config['ADMIN_USERNAME'],
            os.getenv('ADMIN2_USERNAME', '').strip()
        }

        if username in reserved:
            return jsonify(
                error=(
                    'Tên đăng nhập này được dành riêng '
                    'cho quản trị viên.'
                )
            ), 409

        try:
            with connect(
                app.config['DATABASE_PATH']
            ) as db:
                db.execute(
                    '''INSERT INTO users
                       (username, password_hash, is_admin, approved)
                       VALUES (?, ?, 0, 1)''',
                    (
                        username,
                        generate_password_hash(password)
                    )
                )

        except DB_INTEGRITY_ERRORS:
            return jsonify(
                error='Tên đăng nhập đã tồn tại.'
            ), 409

        except Exception:
            app.logger.exception('Lỗi đăng ký tài khoản')

            return jsonify(
                error='Có lỗi khi đăng ký tài khoản.'
            ), 500

        return jsonify(
            status='approved',
            message=(
                'Đăng ký thành công! '
                'Bạn có thể đăng nhập ngay.'
            )
        ), 201

    # ---------------------- ĐĂNG NHẬP ----------------------

    @app.post('/api/login')
    def login():
        d = request.get_json(silent=True) or {}

        username = str(
            d.get('username', '')
        ).strip()

        password = str(
            d.get('password', '')
        )

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            row = db.execute(
                'SELECT * FROM users WHERE username=?',
                (username,)
            ).fetchone()

        if not row or not check_password_hash(
            row['password_hash'],
            password
        ):
            return jsonify(
                error='Sai tên đăng nhập hoặc mật khẩu.'
            ), 401

        if not row['approved']:
            return jsonify(
                error=(
                    'Tài khoản đang chờ '
                    'quản trị viên duyệt.'
                )
            ), 403

        session.clear()
        session['user_id'] = row['id']

        return jsonify(
            id=row['id'],
            username=row['username'],
            is_admin=bool(row['is_admin']),
            approved=bool(row['approved'])
        )

    # ----------------------- ĐĂNG XUẤT ---------------------

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    # ---------------------- THÔNG TIN ME -------------------

    @app.get('/api/me')
    def me():
        user = current_user()

        if not user:
            return jsonify(user=None)

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            row = db.execute(
                '''SELECT username, is_admin, approved,
                          avatar_color, bio, created_at
                   FROM users
                   WHERE id=?''',
                (user['id'],)
            ).fetchone()

        return jsonify(
            user=dict(row) if row else None
        )

    # ------------------------- HỒ SƠ -----------------------

    @app.get('/profile')
    def profile_page():
        if not current_user():
            return redirect(url_for('home'))

        return render_template('profile.html')

    @app.put('/api/profile')
    def update_profile():
        user = current_user()

        if not user:
            return jsonify(
                error='Cần đăng nhập.'
            ), 401

        d = request.get_json(silent=True) or {}

        bio = str(
            d.get('bio', '')
        ).strip()

        color = str(
            d.get('avatar_color', '#7c3aed')
        )

        if len(bio) > 240:
            return jsonify(
                error='Giới thiệu tối đa 240 ký tự.'
            ), 400

        if not re.fullmatch(
            r'#[0-9a-fA-F]{6}',
            color
        ):
            return jsonify(
                error='Mã màu avatar không hợp lệ.'
            ), 400

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            db.execute(
                '''UPDATE users
                   SET bio=?, avatar_color=?
                   WHERE id=?''',
                (
                    bio,
                    color,
                    user['id']
                )
            )

        return jsonify(
            ok=True,
            bio=bio,
            avatar_color=color
        )

    # ---------------------- LỊCH SỬ NỘP --------------------

    @app.get('/submissions')
    def submissions_page():
        return render_template('submissions.html')

    @app.get('/submission/<int:submission_id>')
    def submission_page(submission_id):
        user = current_user()

        if not user:
            return redirect(url_for('home'))

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            row = db.execute(
                '''SELECT id, user_id, problem_id, contest_id
                   FROM submissions
                   WHERE id=?''',
                (submission_id,)
            ).fetchone()

            if not row:
                return render_template(
                    'not_found.html'
                ), 404

            is_mine = row['user_id'] == user['id']
            is_admin = bool(user['is_admin'])

            # Không phải bài của mình hoặc admin:
            # phải FULL cùng bài, cùng phạm vi contest.
            if not is_mine and not is_admin:
                if row['contest_id'] is None:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND contest_id IS NULL
                             AND max_score > 0
                             AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id']
                        )
                    ).fetchone()

                else:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND contest_id=?
                             AND max_score > 0
                             AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id'],
                            row['contest_id']
                        )
                    ).fetchone()

                if not full:
                    return render_template(
                        'not_found.html'
                    ), 403

        return render_template(
            'submission_detail.html',
            submission_id=submission_id
        )

    @app.get('/leaderboard')
    def leaderboard_page():
        return redirect(url_for('home'))

    @app.get('/about')
    def about_page():
        return render_template('about.html')

    # ---------------------- TRANG ADMIN --------------------

    @app.get('/admin')
    def admin_page():
        user = current_user()

        if not user or not user['is_admin']:
            return render_template(
                'not_found.html'
            ), 403

        return render_template('admin.html')

    # ---------------------- API SUBMISSIONS ----------------

    @app.get('/api/submissions')
    def submission_history():
        user = current_user()

        if not user:
            return jsonify(
                error='Cần đăng nhập.'
            ), 401

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            rows = db.execute(
                '''SELECT s.id, s.user_id, u.username,
                          s.problem_id, s.language_id, s.verdict,
                          s.score, s.max_score,
                          s.created_at, s.contest_id
                   FROM submissions s
                   JOIN users u ON u.id=s.user_id
                   WHERE u.approved=1
                   ORDER BY s.id DESC
                   LIMIT 500'''
            ).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            item['is_mine'] = (
                item['user_id'] == user['id']
            )
            result.append(item)

        return jsonify(result)

    # ----------------------- XEM CODE ----------------------

    @app.get('/api/submissions/<int:submission_id>/code')
    def submission_code(submission_id):
        user = current_user()

        if not user:
            return jsonify(
                error='Cần đăng nhập.'
            ), 401

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            row = db.execute(
                '''SELECT id, user_id, problem_id, source_code,
                          verdict, score, max_score, contest_id
                   FROM submissions
                   WHERE id=?''',
                (submission_id,)
            ).fetchone()

            if not row:
                return jsonify(
                    error='Không tìm thấy bài nộp.'
                ), 404

            is_mine = row['user_id'] == user['id']
            is_admin = bool(user['is_admin'])

            if not is_mine and not is_admin:
                if row['contest_id'] is None:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND contest_id IS NULL
                             AND max_score > 0
                             AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id']
                        )
                    ).fetchone()

                else:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND contest_id=?
                             AND max_score > 0
                             AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id'],
                            row['contest_id']
                        )
                    ).fetchone()

                if not full:
                    return jsonify(
                        error=(
                            'Bạn cần FULL bài này để '
                            'xem code của người khác.'
                        )
                    ), 403

            return jsonify({
                'id': row['id'],
                'problem_id': row['problem_id'],
                'source_code': row['source_code']
            })

    # --------------------- CHI TIẾT BÀI NỘP ---------------

    @app.get('/api/submissions/<int:submission_id>/status')
    def submission_status(submission_id):
        user = current_user()

        if not user:
            return jsonify(
                error='Cần đăng nhập.'
            ), 401

        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            row = db.execute(
                '''SELECT id, user_id, problem_id, language_id,
                          verdict, score, max_score, details_json,
                          created_at, contest_id
                   FROM submissions
                   WHERE id=?''',
                (submission_id,)
            ).fetchone()

            if not row:
                return jsonify(
                    error='Không tìm thấy bài nộp.'
                ), 404

            is_mine = row['user_id'] == user['id']
            is_admin = bool(user['is_admin'])

            if not is_mine and not is_admin:
                if row['contest_id'] is None:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND contest_id IS NULL
                             AND max_score > 0
                             AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id']
                        )
                    ).fetchone()

                else:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND contest_id=?
                             AND max_score > 0
                             AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id'],
                            row['contest_id']
                        )
                    ).fetchone()

                if not full:
                    return jsonify(
                        error=(
                            'Bạn cần FULL bài này để xem '
                            'chi tiết bài nộp của người khác.'
                        )
                    ), 403

        result = dict(row)

        result['details'] = json.loads(
            result.pop('details_json') or '[]'
        )

        result.pop('user_id', None)
        result['is_mine'] = is_mine

        return jsonify(result)

    # ----------------------- BẢNG XẾP HẠNG -----------------

    @app.get('/api/leaderboard')
    def leaderboard():
        with connect(
            app.config['DATABASE_PATH']
        ) as db:
            rows = db.execute(
                '''SELECT u.username,
                          COALESCE(SUM(s.best_score), 0) score,
                          COUNT(
                              CASE WHEN s.best_score>0 THEN 1 END
                          ) solved
                   FROM users u
                   LEFT JOIN solves s ON s.user_id=u.id
                   WHERE u.approved=1
                   GROUP BY u.id
                   ORDER BY score DESC, solved DESC, u.username
                   LIMIT 100'''
            ).fetchall()

        return jsonify([
            dict(row) for row in rows
        ])

    # --------------------- NỘP BÀI THƯỜNG -----------------

    @app.post('/api/submit')
    def submit():
        user = current_user()

        if not user:
            return jsonify(
                error='Đăng nhập trước khi nộp bài.'
            ), 401

        d = request.get_json(silent=True) or {}

        pid = str(
            d.get('problem_id', '')
        )

        code = d.get('source_code', '')
        language = d.get('language_id', 54)

        if not isinstance(code, str) or not code.strip():
            return jsonify(
                error='Mã nguồn không được để trống.'
            ), 400

        if len(code) > 100000:
            return jsonify(
                error='Mã nguồn vượt quá 100 KB.'
            ), 400

        try:
            language = int(language)
        except (ValueError, TypeError):
            return jsonify(
                error='language_id không hợp lệ.'
            ), 400

        p = next(
            (x for x in problems() if str(x['id']) == pid),
            None
        )

        if not p:
            return jsonify(
                error='Không tìm thấy bài.'
            ), 404

        # Nộp bài thường không truyền contest_id.
        try:
            job_id, submission_id = enqueue(
                app,
                user['id'],
                p,
                code,
                language
            )

        except Exception:
            app.logger.exception('Lỗi tạo bài nộp')
            return jsonify(
                error='Không thể tạo bài nộp. Hãy thử lại.'
            ), 500

        return jsonify(
            submission_id=submission_id,
            job_id=job_id,
            status='Queued',
            message='Đã nhận bài. Đang chấm...'
        ), 202

    # PHẦN 3 SẼ TIẾP TỤC CÁC API CONTEST.
    # =====================================================
    # PHẦN 3: CUỘC THI VÀ BÀI TẬP TRONG CUỘC THI
    # =====================================================

    @app.get('/contests')
    def contests_page():
        return render_template('contests.html')

    @app.get('/contests/<int:contest_id>')
    def contest_page(contest_id):
        contest = get_contest_data(contest_id)

        if not contest:
            return render_template('not_found.html'), 404

        return render_template(
            'contest.html',
            contest=contest
        )

    # ---------------------- DANH SÁCH CUỘC THI ------------

    @app.get('/api/contests')
    def api_contests():
        with connect(db_path) as db:
            rows = db.execute(
                '''SELECT id, title, description,
                          start_time, end_time, is_visible
                   FROM contests
                   WHERE is_visible=1
                   ORDER BY start_time DESC, id DESC'''
            ).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            item['is_visible'] = bool(item['is_visible'])

            try:
                item['state'] = contest_state(item)
            except (ValueError, TypeError, KeyError):
                item['state'] = 'unknown'

            result.append(item)

        return jsonify(result)

    # ---------------------- CHI TIẾT CUỘC THI --------------

    @app.get('/api/contests/<int:contest_id>')
    def api_contest(contest_id):
        contest = get_contest_data(contest_id)

        if not contest:
            return jsonify(
                error='Không tìm thấy cuộc thi.'
            ), 404

        return jsonify(contest)

    # ---------------------- BẢNG XẾP HẠNG CUỘC THI --------

    @app.get('/api/contests/<int:contest_id>/leaderboard')
    def contest_leaderboard(contest_id):
        contest = get_contest_data(contest_id)

        if not contest:
            return jsonify(
                error='Không tìm thấy cuộc thi.'
            ), 404

        with connect(db_path) as db:
            rows = db.execute(
                '''SELECT
                       u.id AS user_id,
                       u.username,
                       COALESCE(SUM(best.score), 0) AS total_score,
                       COUNT(
                           CASE
                               WHEN best.score > 0 THEN 1
                           END
                       ) AS solved
                   FROM users u
                   LEFT JOIN (
                       SELECT
                           user_id,
                           problem_id,
                           MAX(score) AS score
                       FROM submissions
                       WHERE contest_id=?
                       GROUP BY user_id, problem_id
                   ) best ON best.user_id=u.id
                   WHERE u.approved=1
                   GROUP BY u.id, u.username
                   ORDER BY total_score DESC,
                            solved DESC,
                            u.username ASC
                   LIMIT 100''',
                (contest_id,)
            ).fetchall()

        return jsonify([
            dict(row) for row in rows
        ])

    # ---------------------- BÀI NỘP TRONG CUỘC THI --------

    @app.get('/api/contests/<int:contest_id>/submissions')
    def contest_submissions(contest_id):
        user = current_user()

        if not user:
            return jsonify(
                error='Cần đăng nhập.'
            ), 401

        contest = get_contest_data(contest_id)

        if not contest:
            return jsonify(
                error='Không tìm thấy cuộc thi.'
            ), 404

        with connect(db_path) as db:
            rows = db.execute(
                '''SELECT
                       s.id,
                       s.user_id,
                       u.username,
                       s.problem_id,
                       s.language_id,
                       s.verdict,
                       s.score,
                       s.max_score,
                       s.created_at,
                       s.contest_id
                   FROM submissions s
                   JOIN users u ON u.id=s.user_id
                   WHERE s.contest_id=?
                     AND u.approved=1
                   ORDER BY s.id DESC
                   LIMIT 500''',
                (contest_id,)
            ).fetchall()

        result = []

        for row in rows:
            item = dict(row)
            item['is_mine'] = (
                item['user_id'] == user['id']
            )
            result.append(item)

        return jsonify(result)

    # ---------------------- NỘP BÀI TRONG CUỘC THI --------

    @app.post('/api/contests/<int:contest_id>/submit')
    def contest_submit(contest_id):
        user = current_user()

        if not user:
            return jsonify(
                error='Đăng nhập trước khi nộp bài.'
            ), 401

        d = request.get_json(silent=True) or {}

        pid = str(
            d.get('problem_id', '')
        )

        code = d.get('source_code', '')
        language = d.get('language_id', 54)

        if not isinstance(code, str) or not code.strip():
            return jsonify(
                error='Mã nguồn không được để trống.'
            ), 400

        if len(code) > 100000:
            return jsonify(
                error='Mã nguồn vượt quá 100 KB.'
            ), 400

        try:
            language = int(language)
        except (ValueError, TypeError):
            return jsonify(
                error='language_id không hợp lệ.'
            ), 400

        contest = get_contest_data(contest_id)

        if not contest:
            return jsonify(
                error='Không tìm thấy cuộc thi.'
            ), 404

        try:
            state = contest_state(contest)
        except (ValueError, TypeError, KeyError):
            return jsonify(
                error='Thời gian cuộc thi không hợp lệ.'
            ), 500

        if state != 'running':
            return jsonify(
                error='Cuộc thi chưa bắt đầu hoặc đã kết thúc.'
            ), 403

        with connect(db_path) as db:
            member = db.execute(
                '''SELECT problem_id, total_score
                   FROM contest_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

            custom_row = db.execute(
                '''SELECT *
                   FROM contest_custom_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

        if not member:
            return jsonify(
                error='Bài này không thuộc cuộc thi.'
            ), 403

        # Bài do admin tạo riêng trong cuộc thi.
        if custom_row:
            custom = dict(custom_row)

            try:
                subtasks = json.loads(
                    custom.get('subtasks_json') or '[]'
                )
            except (ValueError, TypeError):
                return jsonify(
                    error='Dữ liệu subtasks của bài thi bị lỗi.'
                ), 500

            p = {
                'id': str(custom['problem_id']),
                'title': custom.get('title', ''),
                'statement': custom.get('statement', ''),
                'input_desc': custom.get('input_desc', ''),
                'output_desc': custom.get('output_desc', ''),
                'sample_input': custom.get('sample_input', ''),
                'sample_output': custom.get('sample_output', ''),
                'time_limit': custom.get('time_limit', 1),
                'memory_limit': custom.get('memory_limit', 256000),
                'total_score': float(member['total_score']),
                'subtasks': subtasks
            }

        else:
            # Bài lấy từ ngân hàng đề.
            original = next(
                (
                    x for x in problems()
                    if str(x['id']) == pid
                ),
                None
            )

            if not original:
                return jsonify(
                    error='Không tìm thấy bài trong ngân hàng đề.'
                ), 404

            p = dict(original)
            p['subtasks'] = [
                dict(s) for s in original.get('subtasks', [])
            ]

            # Điều chỉnh điểm subtasks theo tổng điểm của cuộc thi.
            original_total = float(
                original.get('total_score', 0)
            )
            target_total = float(
                member['total_score']
            )

            if original_total <= 0 or target_total <= 0:
                return jsonify(
                    error='Cấu hình điểm bài thi không hợp lệ.'
                ), 500

            ratio = target_total / original_total

            for subtask in p['subtasks']:
                subtask['score'] = (
                    float(subtask['score']) * ratio
                )

            p['total_score'] = target_total

        try:
            job_id, submission_id = enqueue(
                app,
                user['id'],
                p,
                code,
                language,
                contest_id=contest_id
            )

        except Exception:
            app.logger.exception(
                'Lỗi tạo bài nộp trong cuộc thi'
            )

            return jsonify(
                error='Không thể tạo bài nộp. Hãy thử lại.'
            ), 500

        return jsonify(
            submission_id=submission_id,
            job_id=job_id,
            status='Queued',
            message='Đã nhận bài thi. Đang chấm...'
        ), 202

    # ---------------------- SỬA BÀI RIÊNG CỦA CUỘC THI -----

    @app.put(
        '/api/admin/contests/<int:contest_id>/problems/<pid>'
    )
    def admin_edit_contest_problem(contest_id, pid):
        user = admin_required()

        if not user:
            return jsonify(
                error='Bạn không có quyền quản trị.'
            ), 403

        d = request.get_json(silent=True) or {}

        title = str(
            d.get('title', '')
        ).strip()

        statement = str(
            d.get('statement', '')
        ).strip()

        input_desc = str(
            d.get('input_desc', '')
        ).strip()

        output_desc = str(
            d.get('output_desc', '')
        ).strip()

        sample_input = str(
            d.get('sample_input', '')
        )

        sample_output = str(
            d.get('sample_output', '')
        )

        try:
            total_score = float(
                d.get('total_score', 0)
            )

            time_limit = float(
                d.get('time_limit', 1)
            )

            memory_limit = int(
                d.get('memory_limit', 256000)
            )

        except (ValueError, TypeError):
            return jsonify(
                error='Điểm, thời gian hoặc bộ nhớ không hợp lệ.'
            ), 400

        subtasks = d.get('subtasks')

        if not title or not statement:
            return jsonify(
                error='Cần nhập tiêu đề và đề bài.'
            ), 400

        if not isinstance(subtasks, list) or not subtasks:
            return jsonify(
                error='Bài phải có ít nhất một subtask.'
            ), 400

        if total_score <= 0 or time_limit <= 0 or memory_limit <= 0:
            return jsonify(
                error='Điểm, thời gian và bộ nhớ phải dương.'
            ), 400

        score_sum = 0

        for subtask in subtasks:
            if not isinstance(subtask, dict):
                return jsonify(
                    error='Subtask không hợp lệ.'
                ), 400

            try:
                score = float(
                    subtask.get('score', 0)
                )
            except (ValueError, TypeError):
                return jsonify(
                    error='Điểm subtask không hợp lệ.'
                ), 400

            tests = subtask.get('tests')

            if score <= 0:
                return jsonify(
                    error='Điểm subtask phải dương.'
                ), 400

            if not isinstance(tests, list) or not tests:
                return jsonify(
                    error='Mỗi subtask cần ít nhất một test.'
                ), 400

            score_sum += score

        if abs(score_sum - total_score) > 1e-9:
            return jsonify(
                error='Tổng điểm subtasks phải bằng total_score.'
            ), 400

        with connect(db_path) as db:
            exists = db.execute(
                '''SELECT 1
                   FROM contest_custom_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

            if not exists:
                return jsonify(
                    error='Không tìm thấy bài tập riêng của cuộc thi.'
                ), 404

            db.execute(
                '''UPDATE contest_custom_problems
                   SET title=?,
                       statement=?,
                       input_desc=?,
                       output_desc=?,
                       total_score=?,
                       sample_input=?,
                       sample_output=?,
                       time_limit=?,
                       memory_limit=?,
                       subtasks_json=?
                   WHERE contest_id=? AND problem_id=?''',
                (
                    title,
                    statement,
                    input_desc,
                    output_desc,
                    total_score,
                    sample_input,
                    sample_output,
                    time_limit,
                    memory_limit,
                    json.dumps(
                        subtasks,
                        ensure_ascii=False
                    ),
                    contest_id,
                    pid
                )
            )

            db.execute(
                '''UPDATE contest_problems
                   SET total_score=?
                   WHERE contest_id=? AND problem_id=?''',
                (
                    total_score,
                    contest_id,
                    pid
                )
            )

        return jsonify(
            ok=True,
            message='Đã cập nhật bài tập trong cuộc thi.'
        )

    # HẾT PHẦN 3.
    # =====================================================
    # PHẦN 4: QUẢN TRỊ CUỘC THI
    # =====================================================

    @app.get('/api/admin/contests')
    def admin_list_contests():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        with connect(db_path) as db:
            rows = db.execute(
                '''SELECT *
                   FROM contests
                   ORDER BY id DESC'''
            ).fetchall()

        return jsonify([dict(row) for row in rows])

    @app.post('/api/admin/contests')
    def admin_create_contest():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        d = request.get_json(silent=True) or {}

        title = str(d.get('title', '')).strip()
        description = str(d.get('description', '')).strip()
        start_time = str(d.get('start_time', '')).strip()
        end_time = str(d.get('end_time', '')).strip()
        is_visible = bool(d.get('is_visible', True))
        problem_list = d.get('problems', [])

        if not title:
            return jsonify(error='Tên cuộc thi không được để trống.'), 400

        if not isinstance(problem_list, list):
            return jsonify(error='Danh sách bài tập không hợp lệ.'), 400

        try:
            start = parse_contest_time(start_time)
            end = parse_contest_time(end_time)
        except ValueError as e:
            return jsonify(error=str(e)), 400

        if end <= start:
            return jsonify(error='Thời gian kết thúc phải sau thời gian bắt đầu.'), 400

        try:
            with connect(db_path) as db:
                cur = db.execute(
                    '''INSERT INTO contests
                       (title, description, start_time, end_time, is_visible)
                       VALUES (?, ?, ?, ?, ?)''',
                    (
                        title,
                        description,
                        start_time,
                        end_time,
                        int(is_visible)
                    )
                )

                contest_id = cur.lastrowid

                for position, item in enumerate(problem_list):
                    if not isinstance(item, dict):
                        raise ValueError('Một bài tập trong danh sách không hợp lệ.')

                    pid = str(item.get('problem_id', item.get('id', ''))).strip()

                    if not pid:
                        raise ValueError('Có bài tập thiếu ID.')

                    try:
                        score = float(item.get('total_score', 0))
                    except (ValueError, TypeError):
                        raise ValueError('Điểm bài tập không hợp lệ.')

                    if score <= 0:
                        raise ValueError('Điểm bài tập phải dương.')

                    custom = item.get('custom')

                    if custom:
                        subtasks = custom.get('subtasks', [])

                        if not isinstance(subtasks, list) or not subtasks:
                            raise ValueError('Bài tự tạo cần có subtasks.')

                        subtask_sum = 0

                        for subtask in subtasks:
                            if not isinstance(subtask, dict):
                                raise ValueError('Subtask không hợp lệ.')

                            try:
                                sub_score = float(subtask.get('score', 0))
                            except (ValueError, TypeError):
                                raise ValueError('Điểm subtask không hợp lệ.')

                            if sub_score <= 0:
                                raise ValueError('Điểm subtask phải dương.')

                            tests = subtask.get('tests')

                            if not isinstance(tests, list) or not tests:
                                raise ValueError('Mỗi subtask phải có test.')

                            subtask_sum += sub_score

                        if abs(subtask_sum - score) > 1e-9:
                            raise ValueError('Tổng điểm subtasks phải bằng total_score.')

                        custom_title = str(custom.get('title', '')).strip()
                        statement = str(custom.get('statement', '')).strip()

                        if not custom_title or not statement:
                            raise ValueError('Bài tự tạo cần tiêu đề và đề bài.')

                        db.execute(
                            '''INSERT INTO contest_custom_problems
                               (contest_id, problem_id, title, statement,
                                input_desc, output_desc, total_score,
                                sample_input, sample_output, time_limit,
                                memory_limit, subtasks_json)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (
                                contest_id,
                                pid,
                                custom_title,
                                statement,
                                str(custom.get('input_desc', '')),
                                str(custom.get('output_desc', '')),
                                score,
                                str(custom.get('sample_input', '')),
                                str(custom.get('sample_output', '')),
                                float(custom.get('time_limit', 1)),
                                int(custom.get('memory_limit', 256000)),
                                json.dumps(subtasks, ensure_ascii=False)
                            )
                        )

                    else:
                        original = next(
                            (p for p in problems() if str(p['id']) == pid),
                            None
                        )

                        if not original:
                            raise ValueError('Không tìm thấy bài trong ngân hàng: ' + pid)

                    db.execute(
                        '''INSERT INTO contest_problems
                           (contest_id, problem_id, total_score, position)
                           VALUES (?, ?, ?, ?)''',
                        (contest_id, pid, score, position)
                    )

        except ValueError as e:
            return jsonify(error=str(e)), 400
        except Exception:
            app.logger.exception('Không tạo được cuộc thi')
            return jsonify(error='Không thể tạo cuộc thi.'), 500

        return jsonify(
            ok=True,
            contest_id=contest_id,
            message='Đã tạo cuộc thi.'
        ), 201

    @app.put('/api/admin/contests/<int:contest_id>')
    def admin_update_contest(contest_id):
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        d = request.get_json(silent=True) or {}

        title = str(d.get('title', '')).strip()
        description = str(d.get('description', '')).strip()
        start_time = str(d.get('start_time', '')).strip()
        end_time = str(d.get('end_time', '')).strip()
        is_visible = bool(d.get('is_visible', True))

        if not title:
            return jsonify(error='Tên cuộc thi không được để trống.'), 400

        try:
            start = parse_contest_time(start_time)
            end = parse_contest_time(end_time)
        except ValueError as e:
            return jsonify(error=str(e)), 400

        if end <= start:
            return jsonify(error='Thời gian kết thúc phải sau thời gian bắt đầu.'), 400

        with connect(db_path) as db:
            exists = db.execute(
                'SELECT id FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()

            if not exists:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404

            db.execute(
                '''UPDATE contests
                   SET title=?, description=?, start_time=?,
                       end_time=?, is_visible=?
                   WHERE id=?''',
                (
                    title,
                    description,
                    start_time,
                    end_time,
                    int(is_visible),
                    contest_id
                )
            )

        return jsonify(ok=True, message='Đã cập nhật cuộc thi.')

    @app.delete('/api/admin/contests/<int:contest_id>')
    def admin_delete_contest(contest_id):
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        with connect(db_path) as db:
            exists = db.execute(
                'SELECT id FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()

            if not exists:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404

            db.execute(
                'DELETE FROM contest_custom_problems WHERE contest_id=?',
                (contest_id,)
            )
            db.execute(
                'DELETE FROM contest_problems WHERE contest_id=?',
                (contest_id,)
            )
            db.execute(
                'DELETE FROM submissions WHERE contest_id=?',
                (contest_id,)
            )
            db.execute(
                'DELETE FROM contests WHERE id=?',
                (contest_id,)
            )

        return jsonify(ok=True, message='Đã xóa cuộc thi.')

    # =====================================================
    # QUẢN TRỊ NGÂN HÀNG ĐỀ
    # =====================================================

    @app.post('/api/admin/problems/save')
    def admin_save_problems():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        try:
            data = problems()
            for p in data:
                validate_problem(p)

            save_problems(data, app.config['PROBLEMS_PATH'])
            update_problems_cache(data)

            return jsonify(
                ok=True,
                count=len(data),
                message='Đã lưu ngân hàng đề.'
            )

        except Exception as e:
            app.logger.exception('Không lưu được ngân hàng đề')
            return jsonify(error=str(e)), 500

    @app.get('/api/admin/problems')
    def admin_get_problems():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        return jsonify(problems())

    @app.post('/api/admin/problems')
    def admin_add_problem():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        d = request.get_json(silent=True) or {}
        p = dict(d)

        if not p.get('id'):
            p['id'] = 'TT' + datetime.now().strftime('%Y%m%d%H%M%S%f')

        p['id'] = str(p['id']).strip()

        try:
            validate_problem(p)
        except (ValueError, TypeError) as e:
            return jsonify(error=str(e)), 400

        data = problems(refresh=True)

        if any(str(old['id']) == p['id'] for old in data):
            return jsonify(error='ID bài tập đã tồn tại.'), 409

        data = list(data) + [p]

        try:
            save_problems(data, app.config['PROBLEMS_PATH'])
            update_problems_cache(data)
        except Exception as e:
            app.logger.exception('Không lưu được bài mới')
            return jsonify(error=str(e)), 500

        return jsonify(
            ok=True,
            problem=p,
            count=len(data),
            message='Đã thêm và lưu bài tập.'
        ), 201

    @app.put('/api/admin/problems/<pid>')
    def admin_update_problem(pid):
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        d = request.get_json(silent=True) or {}
        data = problems(refresh=True)

        index = next(
            (
                i for i, old in enumerate(data)
                if str(old['id']) == str(pid)
            ),
            None
        )

        if index is None:
            return jsonify(error='Không tìm thấy bài tập.'), 404

        updated = dict(d)
        updated['id'] = str(pid)

        try:
            validate_problem(updated)
        except (ValueError, TypeError) as e:
            return jsonify(error=str(e)), 400

        data = list(data)
        data[index] = updated

        try:
            save_problems(data, app.config['PROBLEMS_PATH'])
            update_problems_cache(data)
        except Exception as e:
            app.logger.exception('Không cập nhật được bài tập')
            return jsonify(error=str(e)), 500

        return jsonify(
            ok=True,
            problem=updated,
            message='Đã cập nhật bài tập.'
        )

    @app.post('/api/admin/problems/remove-duplicates')
    def admin_remove_duplicate_problems():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        data = problems(refresh=True)
        cleaned = remove_duplicates(data)

        try:
            save_history(
                db_path,
                data,
                'Trước khi loại bỏ bài trùng lặp'
            )

            save_problems(cleaned, app.config['PROBLEMS_PATH'])
            update_problems_cache(cleaned)

        except Exception as e:
            app.logger.exception('Không dọn được bài trùng')
            return jsonify(error=str(e)), 500

        return jsonify(
            ok=True,
            before=len(data),
            after=len(cleaned),
            removed=len(data) - len(cleaned),
            message='Đã loại bỏ bài trùng lặp.'
        )

    # =====================================================
    # LỊCH SỬ NGÂN HÀNG ĐỀ
    # =====================================================

    @app.get('/api/admin/problem-history')
    def admin_problem_history():
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        try:
            return jsonify(get_history(db_path))
        except Exception as e:
            app.logger.exception('Không đọc được lịch sử đề')
            return jsonify(error=str(e)), 500

    @app.get('/api/admin/problem-history/<history_id>')
    def admin_problem_history_detail(history_id):
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        try:
            detail = get_history_detail(db_path, history_id)
        except Exception as e:
            app.logger.exception('Không đọc được chi tiết lịch sử')
            return jsonify(error=str(e)), 500

        if detail is None:
            return jsonify(error='Không tìm thấy bản lịch sử.'), 404

        return jsonify(detail)

    @app.post('/api/admin/problem-history/<history_id>/restore')
    def admin_restore_problem_history(history_id):
        if not admin_required():
            return jsonify(error='Không có quyền quản trị.'), 403

        try:
            target = restore_history_data(db_path, history_id)

            if not isinstance(target, list):
                return jsonify(error='Dữ liệu lịch sử không hợp lệ.'), 400

            for p in target:
                validate_problem(p)

            current = problems(refresh=True)

            # Kiểm tra toàn bộ ID và cấu trúc trước khi lưu.
            temp_path = Path(app.config['PROBLEMS_PATH']).with_suffix('.restore.tmp')
            temp_path.parent.mkdir(parents=True, exist_ok=True)

            temp_path.write_text(
                json.dumps(target, ensure_ascii=False),
                encoding='utf-8'
            )

            try:
                load_problems(temp_path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()

            save_history(
                db_path,
                current,
                'Trước khi khôi phục lịch sử ' + str(history_id)
            )

            save_problems(target, app.config['PROBLEMS_PATH'])
            update_problems_cache(target)

        except Exception as e:
            app.logger.exception('Không khôi phục được lịch sử đề')
            return jsonify(error=str(e)), 500

        return jsonify(
            ok=True,
            count=len(target),
            message='Đã khôi phục ngân hàng đề.'
        )

    @app.get('/admin/problem-history')
    def admin_problem_history_page():
        if not admin_required():
            return render_template('not_found.html'), 403

        return render_template('problem_history.html')

    @app.get('/admin/bulk-rename')
    def admin_bulk_rename_page():
        if not admin_required():
            return render_template('not_found.html'), 403

        return render_template('bulk_rename.html')

    # =====================================================
    # ĐĂNG KÝ CÁC ROUTE ADMIN CÓ SẴN
    # =====================================================

    register_admin_routes(
        app,
        connect,
        current_user,
        db_path
    )

    return app


# =========================================================
# KHỞI CHẠY ỨNG DỤNG
# =========================================================

app = create_app()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv('PORT', '5000')),
        debug=False
    )

    # Các route sẽ được khai báo trong PHẦN 2, 3 và 4.
