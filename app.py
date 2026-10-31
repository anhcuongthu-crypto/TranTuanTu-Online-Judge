import base64
import urllib.request
import urllib.error
from urllib.parse import quote, urlencode
import json
import xml.etree.ElementTree as ET
import os
import re
import shutil
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, jsonify, request, render_template,
    session, redirect, url_for
)
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth

from oj.database import connect, init_db, is_postgres_path, DB_INTEGRITY_ERRORS
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


def load_problems(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))

    if not isinstance(data, list):
        raise ValueError('Problems JSON phải là danh sách.')

    ids = set()
    for p in data:
        if p.get('id') in ids:
            raise ValueError('Trùng problem id: ' + str(p.get('id')))
        ids.add(p.get('id'))

        try:
            total_score = float(p['total_score'])
            subtask_scores = [
                float(s['score']) for s in p['subtasks']
            ]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError('Điểm không hợp lệ: ' + str(p.get('id')))

        import math

        if (
            not math.isfinite(total_score)
            or total_score <= 0
            or any(
                not math.isfinite(s) or s <= 0
                for s in subtask_scores
            )
            or abs(sum(subtask_scores) - total_score) > 1e-9
        ):
            raise ValueError('Điểm subtasks không khớp ' + str(p.get('id')))

        if not p['subtasks'] or any(not s.get('tests') for s in p['subtasks']):
            raise ValueError('Subtask thiếu test ' + str(p.get('id')))

    return data



def save_problems(data, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(data, list):
        raise ValueError('Ngân hàng đề phải là danh sách.')

    ids = [str(p.get('id', '')) for p in data]

    if any(not pid for pid in ids):
        raise ValueError('Có bài tập thiếu ID.')

    if len(ids) != len(set(ids)):
        raise ValueError('Có ID bài tập bị trùng.')

    content = json.dumps(data, ensure_ascii=False, indent=2)

    # Lưu lên GitHub nếu đã cấu hình token
    if os.getenv('GITHUB_TOKEN'):
        if not os.getenv('GITHUB_OWNER') or not os.getenv('GITHUB_REPO'):
            raise RuntimeError(
                'Thiếu GITHUB_OWNER hoặc GITHUB_REPO.'
            )

        branch = os.getenv('GITHUB_BRANCH', 'main')

        # Đọc phiên bản mới nhất trên GitHub
        _, sha = github_read_problems()

        payload = {
            'message': 'Update problem bank from Online Judge',
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

        # Kiểm tra dữ liệu đã lưu
        saved_data, _ = github_read_problems()

        if saved_data != data:
            raise RuntimeError(
                'Dữ liệu trên GitHub chưa khớp. '
                'Hãy tải lại trang và kiểm tra.'
            )

    # Ghi file cục bộ
    tmp = target.with_suffix(target.suffix + '.tmp')

    try:
        tmp.write_text(content, encoding='utf-8')
        tmp.replace(target)
    finally:
        if tmp.exists():
            tmp.unlink()


def github_request(path, method='GET', payload=None):
    token = os.getenv('GITHUB_TOKEN')
    owner = os.getenv('GITHUB_OWNER')
    repo = os.getenv('GITHUB_REPO')

    if not token or not owner or not repo:
        raise RuntimeError('Thiếu cấu hình GitHub.')

    url = f'https://api.github.com/repos/{owner}/{repo}{path}'

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
        url, data=body, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode('utf-8')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'GitHub API lỗi {e.code}: {detail}')


def github_read_problems():
    branch = quote(os.getenv('GITHUB_BRANCH', 'main'), safe='')
    result = github_request(
        '/contents/data/problems.json?ref=' + branch
    )

    content = result.get('content', '')
    if not content:
        raise RuntimeError('GitHub không trả về nội dung problems.json.')

    data = json.loads(
        base64.b64decode(content).decode('utf-8')
    )

    if not isinstance(data, list):
        raise ValueError('Problems JSON phải là danh sách.')

    return data, result['sha']


def validate_problem(p):
    if (
        not p.get('title')
        or not p.get('statement')
        or not p.get('subtasks')
    ):
        raise ValueError('Thiếu tiêu đề, đề bài hoặc subtasks.')

    import math

    try:
        total_score = float(p.get('total_score', 0))
        subtask_scores = [
            float(s['score']) for s in p['subtasks']
        ]
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('Điểm bài hoặc điểm subtask không hợp lệ.')

    if (
        not math.isfinite(total_score)
        or total_score <= 0
        or any(
            not math.isfinite(score) or score <= 0
            for score in subtask_scores
        )
    ):
        raise ValueError('Điểm bài và điểm subtask phải là số dương hợp lệ.')

    if abs(sum(subtask_scores) - total_score) > 1e-9:
        raise ValueError('Tổng điểm subtasks phải bằng total_score.')

    if any(not s.get('tests') for s in p['subtasks']):
        raise ValueError('Mỗi subtask cần ít nhất một test.')

def initialize_problem_file(app):
    target = Path(app.config['PROBLEMS_PATH'])
    target.parent.mkdir(parents=True, exist_ok=True)

    # Không bao giờ ghi đè file đã tồn tại trên persistent disk.
    if target.exists():
        return

    source = Path(__file__).parent / 'data' / 'problems.json'
    if source.exists():
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
    else:
        target.write_text('[]', encoding='utf-8')
def set_freopen_settings(p, old=None):
    old = old or {}

    use_freopen = p.get(
        'use_freopen',
        old.get('use_freopen', False)
    )

    if not isinstance(use_freopen, bool):
        raise ValueError('Thiết lập freopen không hợp lệ.')

    input_file = str(
        p.get('input_file', old.get('input_file', ''))
    ).strip()

    output_file = str(
        p.get('output_file', old.get('output_file', ''))
    ).strip()

    if use_freopen:
        if (
            not re.fullmatch(r'[A-Za-z0-9_-]+\.INP', input_file)
            or not re.fullmatch(r'[A-Za-z0-9_-]+\.OUT', output_file)
        ):
            raise ValueError(
                'Tên file phải có dạng TEN.INP và TEN.OUT.'
            )
    else:
        input_file = ''
        output_file = ''

    p['use_freopen'] = use_freopen
    p['input_file'] = input_file
    p['output_file'] = output_file


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-change-me'),
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
        SESSION_REFRESH_EACH_REQUEST=True,
        DATABASE_PATH=os.getenv('DATABASE_URL') or os.getenv(
            'DATABASE_PATH',
            str(Path(app.instance_path) / 'online_judge.sqlite3')
        ),
        PROBLEMS_PATH=os.getenv(
            'PROBLEMS_PATH',
            str(Path(__file__).parent / 'data' / 'problems.json')
        ),
        JUDGE0_URL=os.getenv('JUDGE0_URL', 'https://ce.judge0.com'),
        JUDGE0_API_KEY=os.getenv('JUDGE0_API_KEY', ''),
        ADMIN_USERNAME=os.getenv('ADMIN_USERNAME', 'admin'),
        ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD', ''),
        TESTING=False
    )

    if test_config:
        app.config.update(test_config)
    # ==================== GOOGLE OAUTH ====================

    oauth = OAuth(app)
    google = None

    google_client_id = os.getenv('GOOGLE_CLIENT_ID')
    google_client_secret = os.getenv('GOOGLE_CLIENT_SECRET')

    if google_client_id and google_client_secret:
        google = oauth.register(
            name='google',
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url=(
                'https://accounts.google.com/.well-known/openid-configuration'
            ),
            client_kwargs={
                'scope': 'openid email profile'
            }
        )

    if not is_postgres_path(app.config['DATABASE_PATH']):
        Path(app.config['DATABASE_PATH']).parent.mkdir(
            parents=True, exist_ok=True
        )

    initialize_problem_file(app)
    app.logger.info(
        'Database backend: %s',
        'PostgreSQL' if is_postgres_path(app.config['DATABASE_PATH']) else 'SQLite'
    )
    init_db(app.config['DATABASE_PATH'])
    initialize_history(app.config['DATABASE_PATH'])


    # init_db() migrates the configured backend without wiping existing rows.

    if app.config.get('ADMIN_PASSWORD'):
        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                'SELECT id FROM users WHERE username=?',
                (app.config['ADMIN_USERNAME'],)
            ).fetchone()
            if row:
                db.execute(
                    'UPDATE users SET is_admin=1, approved=1 WHERE id=?',
                    (row['id'],)
                )
            else:
                db.execute(
                    '''INSERT INTO users
                       (username, password_hash, is_admin, approved)
                       VALUES (?, ?, 1, 1)''',
                    (
                        app.config['ADMIN_USERNAME'],
                        generate_password_hash(app.config['ADMIN_PASSWORD'])
                    )
                )

   
    problems_cache = None

    def problems(refresh=False):
        nonlocal problems_cache

        if problems_cache is not None and not refresh:
            return problems_cache

        if os.getenv('GITHUB_TOKEN'):
            data, _ = github_read_problems()
        else:
            data = load_problems(app.config['PROBLEMS_PATH'])

        problems_cache = data
        return problems_cache
    def update_problems_cache(data):
        nonlocal problems_cache
        problems_cache = data
        # ==================== AUTO TRANSLATE PROBLEM ====================

    problem_translation_cache = {}

    def translate_problem_text(text):
        text = str(text or "")

        if not text.strip():
            return ""

        if text in problem_translation_cache:
            return problem_translation_cache[text]

        try:
            # Giữ nguyên các đoạn code nằm trong dấu `...`
            code_parts = []

            def protect_code(match):
                code_parts.append(match.group(0))
                return f" OJCODE{len(code_parts) - 1}END "

            protected = re.sub(r"`[^`]*`", protect_code, text)

            # Chia văn bản thành các đoạn nhỏ, giữ nguyên xuống dòng.
            words = re.findall(r"\S+\s*", protected)
            chunks = []
            current = ""

            for word in words:
                if current and len(
                    (current + word).encode("utf-8")
                ) > 450:
                    chunks.append(current)
                    current = ""

                current += word

            if current:
                chunks.append(current)

            translated_chunks = []

            for chunk in chunks:
                url = "https://api.mymemory.translated.net/get?" + urlencode({
                    "q": chunk,
                    "langpair": "vi|en"
                })

                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "TranTu-OJ-Studio/1.0"
                    }
                )

                with urllib.request.urlopen(req, timeout=15) as response:
                    data = json.loads(
                        response.read().decode("utf-8")
                    )

                if data.get("responseStatus") != 200:
                    return text

                translated_chunks.append(
                    data["responseData"]["translatedText"]
                )

            translated = "".join(translated_chunks)

            # Khôi phục các đoạn code ban đầu.
            for i, code in enumerate(code_parts):
                translated = translated.replace(
                    f"OJCODE{i}END", code
                )

            problem_translation_cache[text] = translated
            return translated

        except Exception:
            app.logger.exception("Lỗi dịch đề bài")
            return text    

    admin2_username = os.getenv('ADMIN2_USERNAME', '').strip()
    admin2_password = os.getenv('ADMIN2_PASSWORD', '')

    if admin2_username and admin2_password:
        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                'SELECT id FROM users WHERE username=?',
                (admin2_username,)
            ).fetchone()

            if row:
                db.execute(
                    'UPDATE users SET is_admin=1, approved=1 WHERE id=?',
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

    def current_user():
        uid = session.get('user_id')
        if not uid:
            return None
        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                'SELECT id, username, is_admin, approved FROM users WHERE id=?',
                (uid,)
            ).fetchone()
        return dict(row) if row else None

    def admin_required():
        user = current_user()
        return user if user and user['is_admin'] else None
    @app.context_processor
    def inject_current_user():
        return {'logged_in_user': current_user()}

    def parse_contest_time(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Thiếu thời gian bắt đầu hoặc kết thúc.')
        try:
            result = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ValueError('Thời gian không hợp lệ.')
        if result.tzinfo is not None:
            raise ValueError('Hãy nhập thời gian địa phương.')
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
        with connect(app.config['DATABASE_PATH']) as db:
            contest = db.execute(
                'SELECT * FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()

            if not contest:
                return None

            if not contest['is_visible'] and not allow_hidden:
                return None

            ids = db.execute(
    '''SELECT problem_id, total_score FROM contest_problems
       WHERE contest_id=?
       ORDER BY position, problem_id''',
    (contest_id,)
).fetchall()
            

            custom_rows = db.execute(
                '''SELECT problem_id, title, statement,
                          input_desc, output_desc, total_score,
                          sample_input, sample_output, subtasks_json
                   FROM contest_custom_problems
                   WHERE contest_id=?''',
                (contest_id,)
            ).fetchall()



        item = dict(contest)
        item['is_visible'] = bool(item['is_visible'])
        item['problem_ids'] = [r['problem_id'] for r in ids]

        bank = {str(p['id']): p for p in problems()}
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
                    'subtasks': json.loads(p.get('subtasks_json') or '[]'),
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
                    'subtasks': p.get('subtasks', []),
                    'statement': p.get('statement', ''),
                    'input_desc': p.get('input_desc', ''),
                    'output_desc': p.get('output_desc', ''),
                    'sample_input': p.get('sample_input', ''),
                    'sample_output': p.get('sample_output', '')
                })

        item['state'] = contest_state(item)
        return item

    @app.get('/health')
    def health():
        try:
            return jsonify(ok=True, problem_count=len(problems()))
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    @app.get('/robots.txt')
    def robots_txt():
        return app.response_class(
            """User-agent: *
Allow: /
Disallow: /admin
Disallow: /profile
Disallow: /submission/

Sitemap: https://trantuantu-online-judge.onrender.com/sitemap.xml
""",
            mimetype='text/plain'
        )

    @app.get('/sitemap.xml')
    def sitemap_xml():
        urls = [
            'https://trantuantu-online-judge.onrender.com/',
            'https://trantuantu-online-judge.onrender.com/about',
            'https://trantuantu-online-judge.onrender.com/contests',
        ]

        for p in problems():
            pid = quote(str(p['id']), safe='')
            urls.append(
                'https://trantuantu-online-judge.onrender.com/problems/' + pid
            )
            urls = list(dict.fromkeys(urls))

        root = ET.Element(
            'urlset',
            xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'
        )

        for url in urls:
            item = ET.SubElement(root, 'url')
            ET.SubElement(item, 'loc').text = url

        xml = ET.tostring(
            root,
            encoding='utf-8',
            xml_declaration=True
        )

        return app.response_class(
            xml,
            mimetype='application/xml'
        )
        # ==================== GOOGLE LOGIN ====================

    @app.get('/auth/google')
    def google_login():
        if not google:
            return 'Google Login chưa được cấu hình.', 503

        redirect_uri = os.getenv('GOOGLE_REDIRECT_URI') or url_for(
            'google_callback',
            _external=True
        )

        return google.authorize_redirect(redirect_uri)

    @app.get('/auth/google/callback')
    def google_callback():
        if not google:
            return 'Google Login chưa được cấu hình.', 503

        try:
            token = google.authorize_access_token()

            info = token.get('userinfo')

            if not info:
                info = google.userinfo()

            google_sub = str(info.get('sub', '')).strip()
            email = str(info.get('email', '')).strip().lower()
            email_verified = info.get('email_verified', False)

            if not google_sub or not email or email_verified not in (
                True, 'true', 'True', 1
            ):
                return 'Không xác minh được tài khoản Google.', 400

            with connect(app.config['DATABASE_PATH']) as db:

                # Tìm tài khoản đã liên kết Google.
                row = db.execute(
                    'SELECT id FROM users WHERE google_sub=?',
                    (google_sub,)
                ).fetchone()

                # Nếu chưa có, tìm tài khoản cùng email để liên kết.
                if not row:
                    row = db.execute(
                        'SELECT id FROM users WHERE LOWER(email)=?',
                        (email,)
                    ).fetchone()

                    if row:
                        db.execute(
                            'UPDATE users SET google_sub=?, email=? WHERE id=?',
                            (google_sub, email, row['id'])
                        )

                # Nếu chưa tồn tại thì tạo tài khoản mới.
                if not row:
                    base = email.split('@')[0]
                    base = re.sub(r'[^A-Za-z0-9_]', '', base)
                    base = base[:24]

                    if len(base) < 3:
                        base = 'googleuser'

                    username = base
                    count = 1

                    while db.execute(
                        'SELECT id FROM users WHERE username=?',
                        (username,)
                    ).fetchone():
                        suffix = str(count)
                        username = base[:24 - len(suffix)] + suffix
                        count += 1

                    db.execute(
                        '''INSERT INTO users
                           (username, email, google_sub,
                            password_hash, is_admin, approved)
                           VALUES (?, ?, ?, ?, 0, 1)''',
                        (
                            username,
                            email,
                            google_sub,
                            generate_password_hash(os.urandom(32).hex())
                        )
                    )

                    row = db.execute(
                        'SELECT id FROM users WHERE google_sub=?',
                        (google_sub,)
                    ).fetchone()

            if not row:
                return 'Không thể tạo tài khoản Google.', 500

            session.clear()
            session.permanent = True
            session['user_id'] = row['id']

            return redirect(url_for('home'))

        except Exception:
            app.logger.exception('Lỗi đăng nhập Google')
            return 'Đăng nhập Google thất bại. Vui lòng thử lại.', 500

    @app.get('/')
    def home():
        return render_template('index.html')
    
    @app.get('/problems/<pid>')
    def problem_page(pid):
        p = next((x for x in problems() if str(x['id']) == pid), None)
        if p:
            return render_template('problem.html', problem=p)
        return render_template('not_found.html'), 404

    @app.get('/problems/<pid>/submit')
    def submit_problem_page(pid):
        p = next((x for x in problems() if str(x['id']) == pid), None)
        if p:
            return render_template('submit_problem.html', problem=p)
        return render_template('not_found.html'), 404


    @app.get('/api/problems')
    def api_problems():
        return jsonify([
            {
                'id': p['id'],
                'title': p['title'],
                'category': p.get('category', ''),
                'difficulty': p.get('difficulty', ''),
                'total_score': p['total_score']
            }
            for p in problems()
        ])

    @app.get('/api/problems/<pid>')
    def api_problem(pid):
        p = next((x for x in problems() if x['id'] == pid), None)
        if not p:
            return jsonify(error='Không tìm thấy bài'), 404
        public = {k: v for k, v in p.items() if k != 'subtasks'}
        public['subtasks'] = [
            {'id': s['id'], 'name': s['name'], 'score': s['score']}
            for s in p['subtasks']
        ]
        return jsonify(public)

    # API tự động dịch đề sang tiếng Anh
    @app.get('/api/problems/<pid>/translation')
    def translate_problem_page(pid):
        p = next(
            (x for x in problems() if str(x.get('id')) == str(pid)),
            None
        )

        if not p:
            return jsonify(error='Không tìm thấy bài'), 404

        fields = [
            'title',
            'statement',
            'input_format',
            'output_format',
            'explanation'
        ]

        result = {}

        for field in fields:
            result[field] = translate_problem_text(p.get(field, ''))

        return jsonify(result)

    @app.post('/api/register')
    def register():
        d = request.get_json(silent=True) or {}
        username = str(d.get('username', '')).strip()
        password = str(d.get('password', ''))
        if not re.fullmatch(r'[A-Za-z0-9_]{3,24}', username):
            return jsonify(
                error='Tên đăng nhập 3-24 ký tự, chỉ gồm chữ, số, _.'
            ), 400
        if len(password) < 8:
            return jsonify(error='Mật khẩu tối thiểu 8 ký tự.'), 400
        if username in (
    app.config['ADMIN_USERNAME'],
    os.getenv('ADMIN2_USERNAME', '').strip()
):
            return jsonify(
                error='Tên đăng nhập này được dành riêng cho quản trị viên.'
            ), 409
        try:
            with connect(app.config['DATABASE_PATH']) as db:
                db.execute(
                    '''INSERT INTO users
                       (username, password_hash, is_admin, approved)
                       VALUES (?, ?, 0, 1)''',
                    (username, generate_password_hash(password))
                )
        except DB_INTEGRITY_ERRORS:
            return jsonify(error='Tên đăng nhập đã tồn tại.'), 409
        except Exception:
            app.logger.exception('Lỗi đăng ký tài khoản')
            return jsonify(error='Có lỗi khi đăng ký tài khoản.'), 500
        return jsonify(
            status='approved',
            message='Đăng ký thành công! Bạn có thể đăng nhập ngay.'
        ), 201

    @app.post('/api/login')
    def login():
        d = request.get_json(silent=True) or {}
        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                'SELECT * FROM users WHERE username=?',
                (str(d.get('username', '')).strip(),)
            ).fetchone()
        if not row or not check_password_hash(
            row['password_hash'], str(d.get('password', ''))
        ):
            return jsonify(error='Sai tên đăng nhập hoặc mật khẩu.'), 401
        if not row['approved']:
            return jsonify(
                error='Tài khoản đang chờ quản trị viên duyệt.'
            ), 403
        session.clear()
        session.permanent = True
        session['user_id'] = row['id']
        return jsonify(
            id=row['id'],
            username=row['username'],
            is_admin=bool(row['is_admin']),
            approved=bool(row['approved'])
        )

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/api/me')
    def me():
        user = current_user()
        if not user:
            return jsonify(user=None)
        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                '''SELECT username, is_admin, approved,
                          avatar_color, bio, created_at
                   FROM users WHERE id=?''',
                (user['id'],)
            ).fetchone()
        return jsonify(user=dict(row) if row else None)

    @app.route('/profile', methods=['GET'])
    def profile_page():
        if not current_user():
            return redirect(url_for('home'))
        return render_template('profile.html')
   
    
    
    
    @app.get('/submissions')
    def submissions_page():
        user = current_user()
        if not user:
            return redirect(url_for('home'))

        scope = request.args.get('scope', 'history')
        problem_id = request.args.get('problem_id', '').strip()

        if scope not in ('all', 'mine', 'history'):
            scope = 'history'

        if scope in ('all', 'mine') and not problem_id:
            scope = 'history'

        return render_template(
            'submissions.html',
            scope=scope,
            problem_id=problem_id
        )

   
    @app.get('/submission/<int:submission_id>')
    def submission_page(submission_id):
        user = current_user()
        if not user:
            return redirect(url_for('home'))

        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                'SELECT id, user_id FROM submissions WHERE id=?',
                (submission_id,)
            ).fetchone()

        if not row:
            return render_template('not_found.html'), 404

        if row['user_id'] != user['id'] and not user['is_admin']:
            with connect(app.config['DATABASE_PATH']) as db:
                submission = db.execute(
                    'SELECT problem_id, contest_id FROM submissions WHERE id=?',
                    (submission_id,)
                ).fetchone()

                if submission['contest_id'] is None:
                    full = db.execute(
                        '''SELECT 1 FROM submissions
                           WHERE user_id=? AND problem_id=?
                             AND contest_id IS NULL
                             AND max_score > 0 AND score >= max_score
                           LIMIT 1''',
                        (user['id'], submission['problem_id'])
                    ).fetchone()
                else:
                    full = db.execute(
                        '''SELECT 1 FROM submissions
                           WHERE user_id=? AND problem_id=?
                             AND contest_id=?
                             AND max_score > 0 AND score >= max_score
                           LIMIT 1''',
                        (
                            user['id'],
                            submission['problem_id'],
                            submission['contest_id']
                        )
                    ).fetchone()

            if not full:
                return render_template('not_found.html'), 403

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



    @app.get('/admin')
    def admin_page():
        user = current_user()
        if not user or not user['is_admin']:
            return render_template('not_found.html'), 403
        return render_template('admin.html')

    @app.put('/api/profile')
    def update_profile():
        user = current_user()
        if not user:
            return jsonify(error='Cần đăng nhập.'), 401
        d = request.get_json(silent=True) or {}
        bio = str(d.get('bio', '')).strip()
        color = str(d.get('avatar_color', '#7c3aed'))
        if len(bio) > 240:
            return jsonify(error='Giới thiệu tối đa 240 ký tự.'), 400
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            return jsonify(error='Mã màu avatar không hợp lệ.'), 400
        with connect(app.config['DATABASE_PATH']) as db:
            db.execute(
                'UPDATE users SET bio=?, avatar_color=? WHERE id=?',
                (bio, color, user['id'])
            )
        return jsonify(ok=True, bio=bio, avatar_color=color)

    @app.get('/api/submissions')
    def submission_history():
        user = current_user()
        if not user:
            return jsonify(error='Cần đăng nhập.'), 401

        scope = request.args.get('scope', 'history')
        problem_id = request.args.get('problem_id', '').strip()

        if scope not in ('all', 'mine', 'history'):
            scope = 'history'

        sql = '''
            SELECT s.id, s.user_id, u.username,
                   s.problem_id, s.language_id, s.verdict,
                   s.score, s.max_score,
                   s.created_at, s.contest_id
            FROM submissions s
            JOIN users u ON u.id = s.user_id
            WHERE u.approved = 1
        '''
        params = []

        if scope == 'all' and problem_id:
            sql += ' AND s.problem_id = ? AND s.contest_id IS NULL'
            params.append(problem_id)

        elif scope == 'mine' and problem_id:
            sql += ''' AND s.problem_id = ?
                       AND s.user_id = ?
                       AND s.contest_id IS NULL'''
            params.extend([problem_id, user['id']])

        else:
            sql += ' AND s.user_id = ?'
            params.append(user['id'])

        sql += ' ORDER BY s.id DESC LIMIT 500'

        with connect(app.config['DATABASE_PATH']) as db:
            rows = db.execute(sql, params).fetchall()

        result = []
        for row in rows:
            item = dict(row)
            item['is_mine'] = item['user_id'] == user['id']
            result.append(item)

        return jsonify(result)


    
    @app.get('/api/submissions/<int:submission_id>/code')
    def submission_code(submission_id):
        user = current_user()
        if not user:
            return jsonify(error='Cần đăng nhập.'), 401

        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                '''SELECT id, user_id, problem_id, source_code,
                          verdict, score, max_score, contest_id
                   FROM submissions
                   WHERE id=?''',
                (submission_id,)
            ).fetchone()

            if not row:
                return jsonify(error='Không tìm thấy bài nộp.'), 404

            # Code của chính mình luôn xem được.
            is_mine = row['user_id'] == user['id']

            # Admin được xem tất cả mã nguồn.
            is_admin = bool(user['is_admin'])

            # Người khác chỉ xem được nếu đã FULL cùng bài,
            # trong cùng contest hoặc cùng ngoài contest.
            if not is_mine and not is_admin:
                if row['contest_id'] is None:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND score >= max_score
                             AND contest_id IS NULL
                           LIMIT 1''',
                        (user['id'], row['problem_id'])
                    ).fetchone()
                else:
                    full = db.execute(
                        '''SELECT 1
                           FROM submissions
                           WHERE user_id=?
                             AND problem_id=?
                             AND score >= max_score
                             AND contest_id=?
                           LIMIT 1''',
                        (
                            user['id'],
                            row['problem_id'],
                            row['contest_id']
                        )
                    ).fetchone()

                if not full:
                    return jsonify(
                        error='Bạn cần FULL bài này để xem code của người khác.'
                    ), 403

            return jsonify({
                'id': row['id'],
                'problem_id': row['problem_id'],
                'source_code': row['source_code']
            })

    
    @app.get('/api/submissions/<int:submission_id>/status')
    def submission_status(submission_id):
        user = current_user()
        if not user:
            return jsonify(error='Cần đăng nhập.'), 401

        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                '''SELECT id, user_id, problem_id, language_id,
                          verdict, score, max_score, details_json,
                          created_at, contest_id
                   FROM submissions
                   WHERE id=?''',
                (submission_id,)
            ).fetchone()

            if not row:
                return jsonify(error='Không tìm thấy bài nộp.'), 404

            is_mine = row['user_id'] == user['id']
            is_admin = bool(user['is_admin'])

            # Bài của mình và admin: luôn được xem.
            # Người khác: phải FULL cùng bài, cùng contest.
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
                        (user['id'], row['problem_id'])
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
                        error='Bạn cần FULL bài này để xem chi tiết bài nộp của người khác.'
                    ), 403

        result = dict(row)
        result['details'] = json.loads(
            result.pop('details_json') or '[]'
        )
        result.pop('user_id', None)
        result['is_mine'] = is_mine

        return jsonify(result)


    @app.get('/api/leaderboard')
    def leaderboard():
        with connect(app.config['DATABASE_PATH']) as db:
            rows = db.execute(
                '''SELECT u.username,
                          COALESCE(SUM(s.best_score), 0) score,
                          COUNT(CASE WHEN s.best_score>0 THEN 1 END) solved
                   FROM users u
                   LEFT JOIN solves s ON s.user_id=u.id
                   WHERE u.approved=1
                   GROUP BY u.id
                   ORDER BY score DESC, solved DESC, u.username
                   LIMIT 100'''
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @app.post('/api/submit')
    def submit():
        user = current_user()
        if not user:
            return jsonify(error='Đăng nhập trước khi nộp bài.'), 401
        d = request.get_json(silent=True) or {}
        pid = str(d.get('problem_id', ''))
        code = d.get('source_code', '')
        language = d.get('language_id', 54)
        p = next((x for x in problems() if x['id'] == pid), None)
        if not p:
            return jsonify(error='Không tìm thấy bài.'), 404
        if not isinstance(code, str) or not code.strip() or len(code) > 100000:
            return jsonify(error='Mã nguồn trống hoặc vượt 100 KB.'), 400
        try:
            language = int(language)
        except (ValueError, TypeError):
            return jsonify(error='language_id không hợp lệ.'), 400
        job_id, submission_id = enqueue(
            app, user['id'], p, code, language
        )
        return jsonify(
            submission_id=submission_id,
            job_id=job_id,
            status='Queued',
            message='Đã nhận bài. Đang chấm...'
        ), 202

    # ==================== CONTEST PAGES ====================

    @app.get('/contests')
    def contests_page():
        return render_template('contests.html')

    @app.get('/contests/<int:contest_id>')
    def contest_page(contest_id):
        return render_template('contest_detail.html', contest_id=contest_id)

    # ==================== CONTEST PUBLIC API ====================

    @app.get('/api/contests')
    def api_contests():
        user = current_user()
        with connect(app.config['DATABASE_PATH']) as db:
            if user and user['is_admin']:
                rows = db.execute(
                    'SELECT * FROM contests ORDER BY start_time DESC, id DESC'
                ).fetchall()
            else:
                rows = db.execute(
                    '''SELECT * FROM contests WHERE is_visible=1
                       ORDER BY start_time DESC, id DESC'''
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['is_visible'] = bool(item['is_visible'])
            item['state'] = contest_state(item)
            result.append(item)
        return jsonify(result)

    
    @app.get('/api/contests/<int:contest_id>')
    def api_contest_detail(contest_id):
        app.logger.info("API CONTEST DETAIL CALLED: %s", contest_id)

        user = current_user()
        item = get_contest_data(
            contest_id, bool(user and user['is_admin'])
        )

        if not item:
            return jsonify(error='Không tìm thấy cuộc thi.'), 404

        return jsonify(item)

        
    @app.get('/api/contests/<int:contest_id>/leaderboard')
    def contest_leaderboard(contest_id):
        user = current_user()

        with connect(app.config['DATABASE_PATH']) as db:
            contest = db.execute(
                'SELECT id, is_visible FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()

            if not contest:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404

            if not contest['is_visible'] and not (
                user and user['is_admin']
            ):
                return jsonify(error='Không tìm thấy cuộc thi.'), 404

            rows = db.execute(
                '''SELECT u.username,
                          COALESCE(SUM(best.score), 0) AS score,
                          COUNT(
                              CASE WHEN best.solved=1 THEN 1 END
                          ) AS solved
                   FROM users u
                   LEFT JOIN (
                       SELECT user_id, problem_id,
                              MAX(score) AS score,
                              MAX(
                                  CASE WHEN verdict='Accepted'
                                       THEN 1 ELSE 0 END
                              ) AS solved
                       FROM submissions
                       WHERE contest_id=?
                         AND verdict NOT IN (
                             'Queued', 'Processing',
                             'Judge Unavailable'
                         )
                       GROUP BY user_id, problem_id
                   ) best ON best.user_id=u.id
                   WHERE u.approved=1
                   GROUP BY u.id
                   ORDER BY score DESC, solved DESC, u.username ASC''',
                (contest_id,)
            ).fetchall()

        return jsonify([dict(row) for row in rows])


    
    # ==================== CONTEST SUBMISSIONS HISTORY ====================

    @app.get('/api/contests/<int:contest_id>/submissions')
    def contest_submissions_history(contest_id):
        user = current_user()

        if not user:
            return jsonify(error='Cần đăng nhập.'), 401

        with connect(app.config['DATABASE_PATH']) as db:
            contest = db.execute(
                'SELECT id, is_visible FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()

            if not contest:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404

            if not contest['is_visible'] and not user['is_admin']:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404

            rows = db.execute(
                '''SELECT s.id, s.user_id, u.username,
                          s.problem_id, s.language_id, s.verdict,
                          s.score, s.max_score, s.created_at,
                          s.contest_id
                   FROM submissions s
                   JOIN users u ON u.id = s.user_id
                   WHERE s.contest_id = ?
                     AND u.approved = 1
                   ORDER BY s.id DESC
                   LIMIT 500''',
                (contest_id,)
            ).fetchall()

        # Lấy tên đề để giao diện hiển thị dễ hiểu hơn.
        contest_data = get_contest_data(
            contest_id, allow_hidden=bool(user['is_admin'])
        )

        problem_titles = {}
        if contest_data:
            for p in contest_data['problems']:
                problem_titles[str(p['id'])] = p['title']

        result = []

        for row in rows:
            item = dict(row)
            item['is_mine'] = item['user_id'] == user['id']
            item['problem_title'] = problem_titles.get(
                str(item['problem_id']),
                str(item['problem_id'])
            )
            result.append(item)

        return jsonify(result)

    # ==================== CONTEST SUBMISSION ====================

    @app.post('/api/contests/<int:contest_id>/submit')
    def contest_submit(contest_id):
        user = current_user()
        if not user:
            return jsonify(error='Đăng nhập trước khi nộp bài.'), 401
        d = request.get_json(silent=True) or {}
        pid = str(d.get('problem_id', ''))
        code = d.get('source_code', '')
        language = d.get('language_id', 54)
        if not isinstance(code, str) or not code.strip() or len(code) > 100000:
            return jsonify(error='Mã nguồn trống hoặc vượt 100 KB.'), 400
        try:
            language = int(language)
        except (ValueError, TypeError):
            return jsonify(error='language_id không hợp lệ.'), 400
        with connect(app.config['DATABASE_PATH']) as db:
            contest = db.execute(
                'SELECT * FROM contests WHERE id=? AND is_visible=1',
                (contest_id,)
            ).fetchone()
            if not contest:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404
            member = db.execute(
    '''SELECT total_score FROM contest_problems
       WHERE contest_id=? AND problem_id=?''',
    (contest_id, pid)
).fetchone()
        now = datetime.now()
        start = parse_contest_time(contest['start_time'])
        end = parse_contest_time(contest['end_time'])
        if now < start:
            return jsonify(error='Cuộc thi chưa bắt đầu.'), 403
        if now >= end:
            return jsonify(error='Cuộc thi đã kết thúc.'), 403
        if not member:
            return jsonify(error='Bài này không thuộc cuộc thi.'), 403
       
        with connect(app.config['DATABASE_PATH']) as db:
            row = db.execute(
                '''SELECT * FROM contest_custom_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

        if row:
            p = {
                'id': row['problem_id'],
                'title': row['title'],
                'statement': row['statement'],
                'input_desc': row['input_desc'],
                'output_desc': row['output_desc'],
                'subtasks': json.loads(row['subtasks_json']),
                'total_score': row['total_score'],
                'time_limit': row['time_limit'],
                'memory_limit': row['memory_limit']
            }
        else:
            p = next((x for x in problems() if str(x['id']) == pid), None)

        if not p:
            return jsonify(error='Không tìm thấy bài.'), 404

        job_id, submission_id = enqueue(
            app, user['id'], p, code, language, contest_id=contest_id
        )

        return jsonify(
            submission_id=submission_id,
            job_id=job_id,
            status='Queued',
            message='Đã nhận bài thi. Đang chấm...'
        ), 202
    
    # SỬA NỘI DUNG BÀI RIÊNG TRONG CONTEST
    @app.put('/api/admin/contests/<int:contest_id>/problems/<pid>')
    def admin_update_contest_problem(contest_id, pid):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403

        d = request.get_json(silent=True) or {}

        with connect(app.config['DATABASE_PATH']) as db:
            old = db.execute(
                '''SELECT * FROM contest_custom_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

        if not old:
            return jsonify(
                error='Không tìm thấy bài riêng trong contest.'
            ), 404

        title = str(d.get('title', old['title'] or '')).strip()
        statement = str(
            d.get('statement', old['statement'] or '')
        ).strip()
        input_desc = str(
            d.get('input_desc', old['input_desc'] or '')
        ).strip()
        output_desc = str(
            d.get('output_desc', old['output_desc'] or '')
        ).strip()

        if not title or not statement:
            return jsonify(
                error='Tên bài và đề bài không được để trống.'
            ), 400

        try:
            subtasks = d.get('subtasks')
            if subtasks is None:
                subtasks = json.loads(old['subtasks_json'] or '[]')

            total_score = float(
                d.get('total_score', old['total_score'])
            )
            time_limit = float(
                d.get('time_limit', old['time_limit'])
            )
            memory_limit = int(
                d.get('memory_limit', old['memory_limit'])
            )

            if (total_score <= 0 or time_limit <= 0
                    or memory_limit <= 0):
                raise ValueError()

            if not isinstance(subtasks, list) or not subtasks:
                return jsonify(
                    error='Bài phải có ít nhất một subtask.'
                ), 400

            score_sum = 0
            subtask_ids = set()

            for s in subtasks:
                if not isinstance(s, dict):
                    raise ValueError()

                sid = str(s.get('id', '')).strip()
                name = str(s.get('name', '')).strip()
                score = float(s.get('score', 0))
                tests = s.get('tests')

                if (not sid or not name or score <= 0
                        or sid in subtask_ids
                        or not isinstance(tests, list)
                        or not tests):
                    raise ValueError()

                subtask_ids.add(sid)
                score_sum += score

                for t in tests:
                    if (not isinstance(t, dict)
                            or not isinstance(t.get('input'), str)
                            or not isinstance(t.get('output'), str)):
                        raise ValueError()

            if abs(score_sum - total_score) > 1e-9:
                return jsonify(
                    error='Tổng điểm subtask phải bằng điểm tối đa.'
                ), 400

        except (ValueError, TypeError, OverflowError):
            return jsonify(
                error='Dữ liệu subtask hoặc giới hạn không hợp lệ.'
            ), 400

        with connect(app.config['DATABASE_PATH']) as db:
            db.execute(
                '''UPDATE contest_custom_problems
                   SET title=?, statement=?, input_desc=?, output_desc=?,
                       subtasks_json=?, total_score=?, time_limit=?,
                       memory_limit=?, sample_input=?, sample_output=?
                   WHERE contest_id=? AND problem_id=?''',
                (
                    title,
                    statement,
                    input_desc,
                    output_desc,
                    json.dumps(subtasks, ensure_ascii=False),
                    total_score,
                    time_limit,
                    memory_limit,
                    str(d.get(
                        'sample_input', old['sample_input'] or ''
                    )),
                    str(d.get(
                        'sample_output', old['sample_output'] or ''
                    )),
                    contest_id,
                    pid
                )
            )

        return jsonify(
            ok=True,
            message='Đã cập nhật bài riêng trong contest.'
        )

    # ==================== ADMIN CONTEST API ====================

    @app.get('/api/admin/contests')
    def admin_list_contests():
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        with connect(app.config['DATABASE_PATH']) as db:
            rows = db.execute(
                'SELECT * FROM contests ORDER BY id DESC'
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['is_visible'] = bool(item['is_visible'])
            item['state'] = contest_state(item)
            result.append(item)
        return jsonify(result)

    
    
    @app.post('/api/admin/contests')
    def admin_create_contest():
        admin = admin_required()
        if not admin:
            return jsonify(error='Chỉ admin.'), 403

        d = request.get_json(silent=True) or {}

        title = str(d.get('title', '')).strip()
        description = str(d.get('description', '')).strip()
        problem_ids = d.get('problem_ids', [])
        custom_problems = d.get('custom_problems', [])
        visible = d.get('is_visible', True)

        if not title or len(title) > 160:
            return jsonify(error='Tên cuộc thi không hợp lệ.'), 400

        if len(description) > 5000:
            return jsonify(error='Mô tả tối đa 5000 ký tự.'), 400

        if not isinstance(visible, bool):
            return jsonify(error='Trạng thái hiển thị không hợp lệ.'), 400

        if not isinstance(problem_ids, list):
            return jsonify(error='problem_ids phải là danh sách.'), 400

        if not isinstance(custom_problems, list):
            return jsonify(error='custom_problems phải là danh sách.'), 400

        if not problem_ids and not custom_problems:
            return jsonify(
                error='Chọn ít nhất một bài ngân hàng hoặc thêm bài riêng.'
            ), 400

        try:
            start = parse_contest_time(d.get('start_time'))
            end = parse_contest_time(d.get('end_time'))

            if end <= start:
                return jsonify(
                    error='Thời gian kết thúc phải sau thời gian bắt đầu.'
                ), 400

            bank_problems = {
                str(p['id']): p for p in problems()
            }

            # Kiểm tra các bài lấy từ ngân hàng đề.
            ids = []

            for value in problem_ids:
                pid = str(value).strip()

                if not pid or pid not in bank_problems:
                    return jsonify(
                        error='Không tìm thấy bài: ' + pid
                    ), 400

                if pid not in ids:
                    ids.append(pid)

            # Kiểm tra các bài riêng của Contest.
            custom_ids = set()
            checked_custom = []

            for p in custom_problems:
                if not isinstance(p, dict):
                    return jsonify(
                        error='Mỗi bài riêng phải là một object.'
                    ), 400

                pid = str(p.get('id', '')).strip()
                problem_title = str(p.get('title', '')).strip()
                statement = str(p.get('statement', '')).strip()

                if not pid or not problem_title or not statement:
                    return jsonify(
                        error='Bài riêng phải có ID, tên và đề bài.'
                    ), 400

                if pid in bank_problems:
                    return jsonify(
                        error=f'ID {pid} đã tồn tại trong ngân hàng đề.'
                    ), 400

                if pid in ids or pid in custom_ids:
                    return jsonify(
                        error=f'ID bài bị trùng: {pid}'
                    ), 400

                subtasks = p.get('subtasks')

                if not isinstance(subtasks, list) or not subtasks:
                    return jsonify(
                        error=f'Bài {pid} phải có ít nhất một subtask.'
                    ), 400

                try:
                    total_score = float(p.get('total_score', 0))
                    time_limit = float(p.get('time_limit', 1))
                    memory_limit = int(p.get('memory_limit', 256000))
                except (ValueError, TypeError, OverflowError):
                    return jsonify(
                        error=f'Thông số bài {pid} không hợp lệ.'
                    ), 400

                if not all(
                    __import__('math').isfinite(x)
                    for x in (total_score, time_limit)
                ):
                    return jsonify(
                        error=f'Thông số bài {pid} không hợp lệ.'
                    ), 400

                if (
                    total_score <= 0
                    or time_limit <= 0
                    or memory_limit <= 0
                ):
                    return jsonify(
                        error=f'Điểm, thời gian và bộ nhớ của {pid} phải dương.'
                    ), 400

                score_sum = 0
                subtask_ids = set()

                for s in subtasks:
                    if not isinstance(s, dict):
                        return jsonify(
                            error=f'Subtask của {pid} không hợp lệ.'
                        ), 400

                    sid = str(s.get('id', '')).strip()
                    name = str(s.get('name', '')).strip()
                    tests = s.get('tests')

                    try:
                        score = float(s.get('score', 0))
                    except (ValueError, TypeError, OverflowError):
                        return jsonify(
                            error=f'Điểm subtask của {pid} không hợp lệ.'
                        ), 400

                    if not __import__('math').isfinite(score):
                        return jsonify(
                            error=f'Điểm subtask của {pid} không hợp lệ.'
                        ), 400

                    if not sid or not name or score <= 0:
                        return jsonify(
                            error=f'Subtask của {pid} thiếu ID, tên hoặc điểm hợp lệ.'
                        ), 400

                    if sid in subtask_ids:
                        return jsonify(
                            error=f'ID subtask bị trùng trong bài {pid}: {sid}'
                        ), 400

                    if not isinstance(tests, list) or not tests:
                        return jsonify(
                            error=f'Mỗi subtask của {pid} phải có test.'
                        ), 400

                    for t in tests:
                        if (
                            not isinstance(t, dict)
                            or not isinstance(t.get('input'), str)
                            or not isinstance(t.get('output'), str)
                        ):
                            return jsonify(
                                error=f'Test của bài {pid} phải có input và output dạng chuỗi.'
                            ), 400

                    subtask_ids.add(sid)
                    score_sum += score

                if abs(score_sum - total_score) > 1e-9:
                    return jsonify(
                        error=f'Tổng điểm subtasks của {pid} phải bằng total_score.'
                    ), 400

                custom_ids.add(pid)
                checked_custom.append({
                    **p,
                    'id': pid,
                    'title': problem_title,
                    'statement': statement,
                    'total_score': total_score,
                    'time_limit': time_limit,
                    'memory_limit': memory_limit
                })

        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:
            app.logger.exception('Lỗi kiểm tra dữ liệu Contest')
            return jsonify(error='Dữ liệu Contest không hợp lệ: ' + str(exc)), 400

        try:
            with connect(app.config['DATABASE_PATH']) as db:
                cur = db.execute(
                    '''INSERT INTO contests
                       (title, description, start_time, end_time,
                        is_visible, created_by)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (
                        title,
                        description,
                        start.isoformat(timespec='minutes'),
                        end.isoformat(timespec='minutes'),
                        int(visible),
                        admin['id']
                    )
                )

                contest_id = cur.lastrowid

                # Lưu các bài lấy từ ngân hàng đề.
                for i, pid in enumerate(ids):
                    db.execute(
                        '''INSERT INTO contest_problems
                           (contest_id, problem_id, position, total_score)
                           VALUES (?, ?, ?, ?)''',
                        (
                            contest_id,
                            pid,
                            i,
                            float(bank_problems[pid]['total_score'])
                        )
                    )

                # Lưu đề riêng và danh sách bài thi của Contest.
                for i, p in enumerate(checked_custom, start=len(ids)):
                    pid = p['id']

                    db.execute(
                        '''INSERT INTO contest_custom_problems
                           (contest_id, problem_id, title, statement,
                            input_desc, output_desc, subtasks_json,
                            total_score, time_limit, memory_limit,
                            sample_input, sample_output)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (
                            contest_id,
                            pid,
                            p['title'],
                            p['statement'],
                            str(p.get('input_desc', '')),
                            str(p.get('output_desc', '')),
                            json.dumps(p['subtasks'], ensure_ascii=False),
                            p['total_score'],
                            p['time_limit'],
                            p['memory_limit'],
                            str(p.get('sample_input', '')),
                            str(p.get('sample_output', ''))
                        )
                    )

                    db.execute(
                        '''INSERT INTO contest_problems
                           (contest_id, problem_id, position, total_score)
                           VALUES (?, ?, ?, ?)''',
                        (
                            contest_id,
                            pid,
                            i,
                            p['total_score']
                        )
                    )

        except DB_INTEGRITY_ERRORS as exc:
            return jsonify(
                error='Không lưu được Contest do dữ liệu trùng hoặc không hợp lệ: '
                      + str(exc)
            ), 400
        except Exception as exc:
            app.logger.exception('Không tạo được Contest')
            return jsonify(
                error='Lỗi khi lưu Contest: ' + str(exc)
            ), 500

        return jsonify(ok=True, id=contest_id), 201



    @app.put('/api/admin/contests/<int:contest_id>')
    def admin_update_contest(contest_id):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403

        d = request.get_json(silent=True) or {}
        title = str(d.get('title', '')).strip()
        description = str(d.get('description', '')).strip()
        visible = d.get('is_visible', True)

        if not title or len(title) > 160:
            return jsonify(error='Tên cuộc thi không hợp lệ.'), 400

        if len(description) > 5000:
            return jsonify(error='Mô tả tối đa 5000 ký tự.'), 400

        if not isinstance(visible, bool):
            return jsonify(error='Trạng thái hiển thị không hợp lệ.'), 400

        try:
            start = parse_contest_time(d.get('start_time'))
            end = parse_contest_time(d.get('end_time'))

            if end <= start:
                return jsonify(
                    error='Thời gian kết thúc phải sau thời gian bắt đầu.'
                ), 400
        except (ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 400

        with connect(app.config['DATABASE_PATH']) as db:
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
                    start.isoformat(timespec='minutes'),
                    end.isoformat(timespec='minutes'),
                    int(visible),
                    contest_id
                )
            )

        return jsonify(
            ok=True,
            id=contest_id,
            message='Đã cập nhật thông tin Contest.'
        )



    @app.delete('/api/admin/contests/<int:contest_id>')
    def admin_delete_contest(contest_id):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        with connect(app.config['DATABASE_PATH']) as db:
            exists = db.execute(
                'SELECT id FROM contests WHERE id=?',
                (contest_id,)
            ).fetchone()
            if not exists:
                return jsonify(error='Không tìm thấy cuộc thi.'), 404
            submissions = db.execute(
                'SELECT COUNT(*) AS n FROM submissions WHERE contest_id=?',
                (contest_id,)
            ).fetchone()['n']
            if submissions:
                return jsonify(
                    error='Cuộc thi đã có bài nộp, không thể xóa.'
                ), 409
            db.execute('DELETE FROM contests WHERE id=?', (contest_id,))
        return jsonify(ok=True)
            # ==================== SỬA TEST TRONG CONTEST ====================

    @app.put(
        '/api/admin/contests/<int:contest_id>/problems/<pid>/tests'
    )
    def admin_update_contest_tests(contest_id, pid):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403

        d = request.get_json(silent=True) or {}
        subtasks = d.get('subtasks')

        if not isinstance(subtasks, list) or not subtasks:
            return jsonify(
                error='Phải có ít nhất một subtask.'
            ), 400

        # Kiểm tra cấu trúc subtasks và test.
        ids = set()
        score_sum = 0

        try:
            for s in subtasks:
                if not isinstance(s, dict):
                    raise ValueError('Subtask không hợp lệ.')

                sid = str(s.get('id', '')).strip()
                name = str(s.get('name', '')).strip()
                score = float(s.get('score', 0))
                tests = s.get('tests')

                if not sid or not name or sid in ids:
                    raise ValueError(
                        'ID subtask thiếu hoặc bị trùng.'
                    )

                if score <= 0 or not __import__('math').isfinite(score):
                    raise ValueError('Điểm subtask không hợp lệ.')

                if not isinstance(tests, list) or not tests:
                    raise ValueError(
                        f'Subtask {sid} phải có ít nhất một test.'
                    )

                for t in tests:
                    if (
                        not isinstance(t, dict)
                        or not isinstance(t.get('input'), str)
                        or not isinstance(t.get('output'), str)
                    ):
                        raise ValueError(
                            f'Test trong subtask {sid} phải có input '
                            'và output dạng chuỗi.'
                        )

                ids.add(sid)
                score_sum += score

        except (ValueError, TypeError, OverflowError) as exc:
            return jsonify(error=str(exc)), 400

        with connect(app.config['DATABASE_PATH']) as db:
            member = db.execute(
                '''SELECT problem_id FROM contest_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

            custom = db.execute(
                '''SELECT * FROM contest_custom_problems
                   WHERE contest_id=? AND problem_id=?''',
                (contest_id, pid)
            ).fetchone()

        if not member:
            return jsonify(
                error='Bài này không thuộc contest.'
            ), 404

        # Trường hợp 1: bài riêng của contest.
        if custom:
            try:
                total_score = float(custom['total_score'])
            except (ValueError, TypeError):
                return jsonify(
                    error='Điểm tối đa của bài không hợp lệ.'
                ), 400

            if abs(score_sum - total_score) > 1e-9:
                return jsonify(
                    error='Tổng điểm subtask phải bằng điểm tối đa.'
                ), 400

            with connect(app.config['DATABASE_PATH']) as db:
                db.execute(
                    '''UPDATE contest_custom_problems
                       SET subtasks_json=?
                       WHERE contest_id=? AND problem_id=?''',
                    (
                        json.dumps(subtasks, ensure_ascii=False),
                        contest_id,
                        pid
                    )
                )

            return jsonify(
                ok=True,
                type='custom',
                message='Đã cập nhật test của bài riêng trong contest.'
            )

        # Trường hợp 2: bài lấy từ ngân hàng đề.
        try:
            bank = problems(refresh=True)
            idx = next(
                (
                    i for i, p in enumerate(bank)
                    if str(p.get('id')) == pid
                ),
                None
            )

            if idx is None:
                return jsonify(
                    error='Không tìm thấy bài trong ngân hàng đề.'
                ), 404

            total_score = float(bank[idx]['total_score'])

            if abs(score_sum - total_score) > 1e-9:
                return jsonify(
                    error='Tổng điểm subtask phải bằng điểm tối đa '
                          'của bài trong ngân hàng.'
                ), 400

            # Chỉ thay tests/subtasks, giữ nguyên các trường khác.
            bank[idx]['subtasks'] = subtasks

            save_problems(bank, app.config['PROBLEMS_PATH'])
            update_problems_cache(bank)

        except Exception as exc:
            app.logger.exception('Lỗi cập nhật test ngân hàng đề')
            return jsonify(
                error='Không lưu được test lên ngân hàng/GitHub: '
                      + str(exc)
            ), 500

        return jsonify(
            ok=True,
            type='bank',
            message='Đã cập nhật test và lưu ngân hàng đề lên GitHub.'
        )

    # ==================== ADMIN PROBLEM API ===================

    # Lưu ngân hàng đề lên GitHub thủ công
    @app.post('/api/admin/problems/save')
    def admin_save_problem_bank():
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403

        if not all(os.getenv(key) for key in (
            'GITHUB_TOKEN',
            'GITHUB_OWNER',
            'GITHUB_REPO'
        )):
            return jsonify(
                error='Chưa cấu hình đủ GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO.'
            ), 500

        try:
            data = problems()
            save_problems(data, app.config['PROBLEMS_PATH'])

            return jsonify(
                ok=True,
                count=len(data),
                message=f'Đã lưu thành công {len(data)} bài tập lên GitHub.'
            )
        except Exception as e:
            return jsonify(error=str(e)), 500
    @app.get('/api/admin/problems')
    def admin_list():
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        return jsonify(problems())

    @app.post('/api/admin/problems')
    def admin_create():
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        d = request.get_json(silent=True) or {}
        try:
            old = problems(refresh=True)
            if not d.get('id') or any(p['id'] == d['id'] for p in old):
                return jsonify(error='ID thiếu hoặc đã tồn tại.'), 400
            set_freopen_settings(d)
            validate_problem(d)
            old.append(d)
            save_problems(old, app.config['PROBLEMS_PATH'])
            update_problems_cache(old)
            return jsonify(ok=True, id=d['id']), 201
        except Exception as e:
            return jsonify(error=str(e)), 400

    @app.put('/api/admin/problems/<pid>')
    def admin_update(pid):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403

        d = request.get_json(silent=True) or {}

        try:
            old = problems()
            idx = next(
                (i for i, p in enumerate(old) if str(p['id']) == pid),
                None
            )

            if idx is None:
                return jsonify(error='Không tìm thấy bài.'), 404

            d['id'] = pid
            d['author'] = str(
                d.get('author', old[idx].get('author', ''))
            ).strip()

            set_freopen_settings(d, old[idx])
            validate_problem(d)

            old[idx] = d

            save_problems(old, app.config['PROBLEMS_PATH'])
            update_problems_cache(old)

            return jsonify(ok=True, id=pid)

        except Exception as e:
            return jsonify(error=str(e)), 400
    # XÓA CÁC BÀI TRÙNG NỘI DUNG
    @app.post('/api/admin/problems/remove-duplicates')
    def admin_remove_duplicates():
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403

        try:
            old = problems()
            new, removed = remove_duplicates(old)

            if not removed:
                return jsonify(
                    ok=True,
                    removed=0,
                    remaining=len(new),
                    message='Không tìm thấy bài trùng.'
                )

            save_history(
                app.config['DATABASE_PATH'],
                'remove_duplicates',
                old,
                new,
                removed
            )

            save_problems(new, app.config['PROBLEMS_PATH'])
            update_problems_cache(new)

            return jsonify(
                ok=True,
                removed=len(removed),
                remaining=len(new),
                message='Đã xóa các bài trùng thành công.'
            )

        except Exception as e:
            app.logger.exception('Lỗi xóa bài trùng')
            return jsonify(error=str(e)), 500

    
    

    # ==================== PROBLEM HISTORY ====================

    @app.get('/api/admin/problem-history')
    def admin_problem_history():
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        try:
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
        except (TypeError, ValueError):
            return jsonify(error='limit/offset không hợp lệ.'), 400
        return jsonify(
            get_history(app.config['DATABASE_PATH'], limit, offset)
        )

    @app.get('/api/admin/problem-history/<int:history_id>')
    def admin_problem_history_detail(history_id):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        item = get_history_detail(
            app.config['DATABASE_PATH'], history_id
        )
        if item is None:
            return jsonify(
                error='Không tìm thấy bản ghi lịch sử.'
            ), 404
        return jsonify(item)

    @app.post('/api/admin/problem-history/<int:history_id>/restore')
    def admin_problem_history_restore(history_id):
        if not admin_required():
            return jsonify(error='Chỉ admin.'), 403
        target = restore_history_data(
            app.config['DATABASE_PATH'], history_id
        )
        if target is None:
            return jsonify(
                error='Không tìm thấy bản ghi lịch sử.'
            ), 404

        try:
            validate_path = Path(
                app.config['PROBLEMS_PATH']
            ).with_suffix('.restore-check.json')
            validate_path.parent.mkdir(parents=True, exist_ok=True)
            validate_path.write_text(
                json.dumps(target, ensure_ascii=False),
                encoding='utf-8'
            )
            try:
                load_problems(validate_path)
            finally:
                validate_path.unlink(missing_ok=True)
        except Exception as exc:
            return jsonify(
                error='Không thể khôi phục dữ liệu: ' + str(exc)
            ), 400

        before = problems()
        save_history(
            app.config['DATABASE_PATH'],
            'restore_history', before, target
        )
        
        

        try:
            save_problems(target, app.config['PROBLEMS_PATH'])
            update_problems_cache(target)
        except Exception as exc:
            app.logger.exception('Lỗi khôi phục ngân hàng đề')
            return jsonify(
                error='Không thể lưu dữ liệu khôi phục: ' + str(exc)
            ), 500

        return jsonify(
            ok=True,
            restored_count=len(target),
            message='Đã khôi phục ngân hàng đề về trạng thái trước thao tác.'
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

    register_admin_routes(
        app, connect, current_user, app.config['DATABASE_PATH']
    )
    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
