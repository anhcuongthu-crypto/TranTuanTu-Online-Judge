import json
import app as app_module
from app import create_app
from oj.database import connect
import oj.job_queue as job_queue


def setup(tmp_path):
    probs = tmp_path / 'problems.json'
    probs.write_text(json.dumps([{
        'id': 'X01', 'title': 'Tổng hai số', 'category': 'Cơ bản', 'difficulty': 'Dễ',
        'statement': 'Cho hai số nguyên a, b. In tổng a+b.',
        'input_format': 'Một dòng gồm hai số nguyên a, b.',
        'output_format': 'In tổng a+b.', 'sample_input': '1 2\n', 'sample_output': '3\n',
        'explanation': '1 + 2 = 3 nên kết quả là 3.',
        'total_score': 100, 'time_limit': 1, 'memory_limit': 256000,
        'subtasks': [{'id': 'all', 'name': 'Toàn bộ dữ liệu', 'score': 100,
                      'tests': [{'input': '1 2\n', 'output': '3\n'}]}]
    }]), encoding='utf8')
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'test', 'DATABASE_PATH': str(tmp_path / 'db.sqlite3'),
        'PROBLEMS_PATH': str(probs), 'ADMIN_USERNAME': 'root', 'ADMIN_PASSWORD': 'verysecurepass'
    })
    return app.test_client()


def register_and_login(client, username='tester'):
    r = client.post('/api/register', json={'username': username, 'password': '12345678'})
    assert r.status_code == 201
    assert r.json['status'] == 'approved'
    assert client.post('/api/login', json={'username': username, 'password': '12345678'}).status_code == 200


def test_health_and_problem_details(tmp_path):
    c = setup(tmp_path)
    assert c.application.config['SESSION_COOKIE_HTTPONLY'] is True
    assert c.application.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
    assert c.application.config['MAX_CONTENT_LENGTH'] == 2 * 1024 * 1024
    assert c.get('/health').json['ok'] is True
    assert c.get('/api/problems').json[0]['id'] == 'X01'
    health = c.get('/health').json
    assert health['problem_bank_loaded'] is True
    assert health['problem_count'] == 1
    detail = c.get('/api/problems/X01').json
    assert detail['sample_input'] == '1 2\n'
    assert detail['sample_output'] == '3\n'
    assert detail['explanation']
    assert detail['subtasks'][0]['score'] == 100


def test_problemset_has_saved_problem_filter(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems')
    assert response.status_code == 200
    assert b'id="filter-saved"' in response.data
    assert 'Chỉ hiển thị bài đã lưu'.encode('utf-8') in response.data




def test_recently_viewed_problem_filter_and_tracking(tmp_path):
    client = setup(tmp_path)
    listing = client.get('/problems')
    assert listing.status_code == 200
    assert b'id="filter-recent"' in listing.data

    detail = client.get('/problems/X01')
    assert detail.status_code in (200, 404)
    if detail.status_code == 200:
        page = detail.get_data(as_text=True)
        assert "trantu-oj:recent-problems:v1" in page
        assert "localStorage.setItem" in page
        title_block = page.split("<title>", 1)[1].split("</title>", 1)[0]
        assert "<script>" not in title_block
        assert "id !== String(problemId)" in page

    script = client.get('/static/app.js')
    assert script.status_code == 200
    source = script.get_data(as_text=True)
    assert "RECENT_PROBLEMS_KEY" in source
    assert "matchesRecent" in source

def test_problem_search_keyboard_shortcuts_are_available(tmp_path):
    client = setup(tmp_path)
    page = client.get('/problems')
    assert page.status_code == 200
    assert b'aria-keyshortcuts="/ Escape"' in page.data
    script = client.get('/static/app.js')
    assert script.status_code == 200
    source = script.get_data(as_text=True)
    assert "event.key === '/'" in source
    assert "event.key === 'Escape'" in source

def test_saved_problems_sync_with_account_and_validate_ids(tmp_path):
    client = setup(tmp_path)

    assert client.get('/api/saved-problems').status_code == 401
    register_and_login(client)

    initial = client.get('/api/saved-problems')
    assert initial.status_code == 200
    assert initial.json['problem_ids'] == []

    saved = client.post('/api/saved-problems', json={
        'problem_ids': ['X01', 'X01'],
        'saved': True
    })
    assert saved.status_code == 200
    assert saved.json['problem_ids'] == ['X01']

    invalid = client.post('/api/saved-problems', json={
        'problem_id': 'NOT_A_REAL_PROBLEM',
        'saved': True
    })
    assert invalid.status_code == 400
    assert client.get('/api/saved-problems').json['problem_ids'] == ['X01']

    removed = client.post('/api/saved-problems', json={
        'problem_id': 'X01',
        'saved': False
    })
    assert removed.status_code == 200
    assert removed.json['problem_ids'] == []


def test_registration_is_immediately_approved_and_username_unique(tmp_path):
    c = setup(tmp_path)
    r = c.post('/api/register', json={'username': 'tester', 'password': '12345678'})
    assert r.status_code == 201
    assert r.json['status'] == 'approved'
    assert c.post('/api/login', json={'username': 'tester', 'password': '12345678'}).status_code == 200
    assert c.get('/api/me').json['user']['username'] == 'tester'
    assert c.get('/api/me').json['user']['approved'] == 1
    assert c.post('/api/register', json={'username': 'tester', 'password': '12345678'}).status_code == 409
    assert c.post('/api/register', json={'username': 'root', 'password': '12345678'}).status_code == 409
    assert c.get('/api/admin/users').status_code == 403


def test_new_user_is_approved_but_not_admin(tmp_path):
    c = setup(tmp_path)
    r = c.post('/api/register', json={'username': 'newstudent', 'password': '12345678'})
    assert r.status_code == 201
    assert c.post('/api/login', json={'username': 'newstudent', 'password': '12345678'}).status_code == 200
    assert c.get('/api/admin/users').status_code == 403
    assert c.post('/api/admin/problems', json={
        'id': 'X02', 'title': 'Test', 'statement': 'test', 'total_score': 100,
        'subtasks': [{'id': 'all', 'name': 'all', 'score': 100,
                      'tests': [{'input': '', 'output': ''}]}]
    }).status_code == 403


def test_submit_requires_login_and_history(tmp_path):
    c = setup(tmp_path)
    assert c.post('/api/submit', json={'problem_id': 'X01', 'source_code': 'int main(){}'}).status_code == 401
    register_and_login(c)
    assert c.get('/api/submissions').status_code == 200
    assert any(row['username'] == 'tester' for row in c.get('/api/leaderboard').json)


def test_global_leaderboard_counts_only_full_solutions_and_shows_highlights(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'partialuser')
    register_and_login(client, 'fulluser')

    app = client.application
    with connect(app.config['DATABASE_PATH']) as db:
        users = {
            row['username']: row['id']
            for row in db.execute(
                'SELECT id, username FROM users WHERE username IN (?, ?)',
                ('partialuser', 'fulluser')
            ).fetchall()
        }
        db.execute(
            'INSERT INTO solves (user_id, problem_id, best_score) VALUES (?, ?, ?)',
            (users['partialuser'], 'X01', 50)
        )
        db.execute(
            'INSERT INTO solves (user_id, problem_id, best_score) VALUES (?, ?, ?)',
            (users['fulluser'], 'X01', 100)
        )

    response = client.get('/api/leaderboard')
    assert response.status_code == 200
    rows = {row['username']: row for row in response.json}

    assert rows['fulluser']['rank'] == 1
    assert rows['fulluser']['score'] == 100
    assert rows['fulluser']['solved'] == 1
    assert rows['fulluser']['highlight'] == '🎯 Đã có FULL'

    assert rows['partialuser']['rank'] == 2
    assert rows['partialuser']['score'] == 50
    assert rows['partialuser']['solved'] == 0
    assert rows['partialuser']['attempted'] == 1
    assert rows['partialuser']['highlight'] == '🚀 Đang chinh phục'


def test_admin_problem_crud_and_delete_is_protected(tmp_path):
    c = setup(tmp_path)
    p = {'id': 'X02', 'title': 'Test', 'statement': 'test', 'total_score': 100,
         'subtasks': [{'id': 'all', 'name': 'all', 'score': 100, 'tests': [{'input': '', 'output': ''}]}]}
    assert c.post('/api/admin/problems', json=p).status_code == 403
    assert c.delete('/api/admin/problems/X01').status_code == 403
    assert c.post('/api/login', json={'username': 'root', 'password': 'verysecurepass'}).status_code == 200
    assert c.post('/api/admin/problems', json=p).status_code == 201
    assert c.put('/api/admin/problems/X02', json={**p, 'title': 'Updated'}).status_code == 200
    assert c.delete('/api/admin/problems/X02').status_code == 200

def test_my_analytics_returns_progressive_achievement_badges(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'badgeuser')

    response = client.get('/api/my-analytics')
    assert response.status_code == 200
    badges = {item['id']: item for item in response.json['achievements']}

    assert badges['first-full']['unlocked'] is False
    assert badges['first-full']['progress'] == 0
    assert badges['solver-10']['target'] == 10
    assert badges['multi-topic']['target'] == 3

    app = client.application
    with connect(app.config['DATABASE_PATH']) as db:
        user = db.execute(
            'SELECT id FROM users WHERE username=?', ('badgeuser',)
        ).fetchone()
        db.execute(
            'INSERT INTO solves (user_id, problem_id, best_score) VALUES (?, ?, ?)',
            (user['id'], 'X01', 100)
        )

    refreshed = client.get('/api/my-analytics')
    refreshed_badges = {
        item['id']: item for item in refreshed.json['achievements']
    }
    assert refreshed_badges['first-full']['unlocked'] is True
    assert refreshed_badges['first-full']['progress'] == 1
    assert refreshed_badges['multi-topic']['progress'] == 1


def test_home_problemset_library_and_brand_assets_render(tmp_path):
    c = setup(tmp_path)

    home = c.get('/')
    assert home.status_code == 200
    assert b'class="hero"' in home.data
    assert b'class="hero-copy"' in home.data
    assert b'home-workflow' in home.data
    assert b'og-cover.svg' in home.data
    assert b'favicon.svg' in home.data

    assert c.get('/problems').status_code == 200
    assert c.get('/library').status_code == 200
    assert c.get('/contests').status_code == 200

    assert c.get('/static/favicon.svg').status_code == 200
    assert c.get('/favicon.ico').status_code == 302
    assert c.get('/static/og-cover.svg').status_code == 200

def test_queue_recovery_replays_only_safe_queued_rows(tmp_path, monkeypatch):
    client = setup(tmp_path)
    register_and_login(client, 'recoveruser')
    app = client.application
    db_path = app.config['DATABASE_PATH']

    with connect(db_path) as db:
        user = db.execute(
            'SELECT id FROM users WHERE username=?', ('recoveruser',)
        ).fetchone()
        user_id = user['id']
        queued = db.execute(
            '''INSERT INTO submissions
               (user_id, problem_id, language_id, source_code, verdict,
                score, max_score, details_json, problem_json)
               VALUES (?, ?, ?, ?, 'Queued', 0, 100, '[]', ?)''',
            (
                user_id, 'X01', 54, 'int main(){return 0;}',
                json.dumps({
                    'id': 'X01', 'total_score': 100,
                    'subtasks': [{
                        'id': 'all', 'name': 'All', 'score': 100,
                        'tests': [{'input': '1 2', 'output': '3'}]
                    }]
                })
            )
        ).lastrowid
        interrupted = db.execute(
            '''INSERT INTO submissions
               (user_id, problem_id, language_id, source_code, verdict,
                score, max_score, details_json, problem_json)
               VALUES (?, ?, ?, ?, 'Processing', 0, 100, '[]', ?)''',
            (user_id, 'X01', 54, 'int main(){}', '{}')
        ).lastrowid
        legacy = db.execute(
            '''INSERT INTO submissions
               (user_id, problem_id, language_id, source_code, verdict,
                score, max_score, details_json)
               VALUES (?, ?, ?, ?, 'Queued', 0, 100, '[]')''',
            (user_id, 'X01', 54, 'int main(){}')
        ).lastrowid

    submitted = []
    monkeypatch.setattr(
        job_queue._pool,
        'submit',
        lambda *args: submitted.append(args)
    )

    # create_app() already performed its startup pass; reset the marker
    # to simulate a fresh process after inserting the stale database rows.
    # Simulate a fresh app process after inserting stale database rows.
    app.extensions.pop('_trantu_queue_recovered', None)
    restored = job_queue.recover_pending(app)
    assert restored == 1
    assert len(submitted) == 1
    assert submitted[0][3] == queued
    assert submitted[0][-1] == 'Starting'

    with connect(db_path) as db:
        rows = {
            row['id']: row
            for row in db.execute(
                '''SELECT id, verdict, problem_json, details_json
                   FROM submissions WHERE id IN (?, ?, ?)''',
                (queued, interrupted, legacy)
            ).fetchall()
        }

    # A replay candidate is atomically claimed before entering the executor.
    assert rows[queued]['verdict'] == 'Starting'
    assert rows[queued]['problem_json']
    # An interrupted Processing row is never blindly submitted again.
    assert rows[interrupted]['verdict'] == 'Judge Unavailable'
    assert rows[interrupted]['problem_json'] is None
    # Old queued rows without a snapshot fail visibly instead of hanging.
    assert rows[legacy]['verdict'] == 'Judge Unavailable'
    assert rows[legacy]['problem_json'] is None

    job_id = submitted[0][2]
    with job_queue._lock:
        job_queue._jobs.pop(job_id, None)
    job_queue._capacity.release()

def test_current_user_cache_ttl_and_profile_invalidation(tmp_path, monkeypatch):
    client = setup(tmp_path)
    register_and_login(client, 'cacheuser')

    app = client.application
    db_path = app.config['DATABASE_PATH']
    real_connect = app_module.connect
    connect_calls = []

    def tracked_connect(path):
        connect_calls.append(path)
        return real_connect(path)

    clock = [100.0]
    monkeypatch.setattr(app_module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(app_module, 'connect', tracked_connect)

    # First request loads the profile from the database.
    assert client.get('/api/me').status_code == 200
    assert connect_calls == [db_path]

    # A second request within the 10-second TTL reuses the cached profile.
    connect_calls.clear()
    clock[0] += 9
    assert client.get('/api/me').status_code == 200
    assert connect_calls == []

    # Once expired, the next request refreshes the profile from the database.
    clock[0] += 2
    assert client.get('/api/me').status_code == 200
    assert connect_calls == [db_path]

    # Updating the profile invalidates the cache immediately, not after TTL.
    connect_calls.clear()
    updated = client.put('/api/profile', json={
        'bio': 'Updated bio',
        'avatar_color': '#123456'
    })
    assert updated.status_code == 200

    connect_calls.clear()
    refreshed = client.get('/api/me')
    assert refreshed.status_code == 200
    assert refreshed.json['user']['bio'] == 'Updated bio'
    assert refreshed.json['user']['avatar_color'] == '#123456'
    assert connect_calls == [db_path]

def test_my_progress_cache_hit_skips_database_connection(tmp_path, monkeypatch):
    client = setup(tmp_path)
    register_and_login(client, 'progresscache')

    # First request populates both the profile cache and progress cache.
    first = client.get('/api/my-progress')
    assert first.status_code == 200

    def unexpected_connect(path):
        raise AssertionError('Progress cache hit should not open the database')

    monkeypatch.setattr(app_module, 'connect', unexpected_connect)
    second = client.get('/api/my-progress')
    assert second.status_code == 200
    assert second.json == first.json


def test_public_contests_cache_hit_skips_database_connection(tmp_path, monkeypatch):
    client = setup(tmp_path)

    # Anonymous public contest data is cached for five seconds.
    first = client.get('/api/contests')
    assert first.status_code == 200

    def unexpected_connect(path):
        raise AssertionError('Contests cache hit should not open the database')

    monkeypatch.setattr(app_module, 'connect', unexpected_connect)
    second = client.get('/api/contests')
    assert second.status_code == 200
    assert second.json == first.json

def test_homepage_recent_problems_continue_learning_section(tmp_path):
    client = setup(tmp_path)
    response = client.get('/')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="home-recent-section"' in page
    assert 'id="home-recent-list"' in page
    assert 'id="clear-home-recent"' in page

    script = client.get('/static/app.js')
    assert script.status_code == 200
    source = script.get_data(as_text=True)
    assert 'loadHomeRecentProblems' in source
    assert "api('/api/problems')" in source
    assert 'RECENT_PROBLEMS_KEY' in source

def test_homepage_current_hero_and_workflow_sections_render(tmp_path):
    client = setup(tmp_path)
    response = client.get('/')
    assert response.status_code == 200

    page = response.get_data(as_text=True)
    assert 'class="hero"' in page
    assert 'class="hero-copy"' in page
    assert 'home-workflow' in page
    assert 'home-shortcut-grid' in page
    assert 'home_hero_title' in page

def test_submission_history_skips_user_join_but_all_scope_stays_global(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'historyowner')
    register_and_login(client, 'historyother')
    assert client.post('/api/login', json={
        'username': 'historyowner', 'password': '12345678'
    }).status_code == 200

    app = client.application
    with connect(app.config['DATABASE_PATH']) as db:
        users = {
            row['username']: row['id']
            for row in db.execute(
                'SELECT id, username FROM users WHERE username IN (?, ?)',
                ('historyowner', 'historyother')
            ).fetchall()
        }
        for username in ('historyowner', 'historyother'):
            db.execute(
                '''INSERT INTO submissions
                   (user_id, problem_id, language_id, source_code, verdict,
                    score, max_score, details_json)
                   VALUES (?, 'X01', 54, ?, 'Accepted', 100, 100, '[]')''',
                (users[username], 'int main(){return 0;}')
            )

    own = client.get('/api/submissions?scope=history&limit=10')
    assert own.status_code == 200
    assert len(own.json) == 1
    assert own.json[0]['username'] == 'historyowner'
    assert own.json[0]['is_mine'] is True

    mine = client.get('/api/submissions?scope=mine&problem_id=X01&limit=10')
    assert mine.status_code == 200
    assert len(mine.json) == 1
    assert mine.json[0]['username'] == 'historyowner'

    all_rows = client.get('/api/submissions?scope=all&problem_id=X01&limit=10')
    assert all_rows.status_code == 200
    assert {row['username'] for row in all_rows.json} == {
        'historyowner', 'historyother'
    }
    assert all(row['is_mine'] == (row['username'] == 'historyowner')
               for row in all_rows.json)
