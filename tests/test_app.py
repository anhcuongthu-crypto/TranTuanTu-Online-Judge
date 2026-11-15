import json
from datetime import datetime, timedelta
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




def test_problemset_can_clear_recently_viewed_history(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems')
    assert response.status_code == 200
    assert b'id="clear-recent-problems"' in response.data

    script = client.get('/static/app.js')
    assert script.status_code == 200
    source = script.get_data(as_text=True)
    assert "recentProblemIds.clear()" in source
    assert "localStorage.removeItem(RECENT_PROBLEMS_KEY)" in source
    assert "id !== String(problemId)" not in source

def test_problem_page_copy_link_control_is_available(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems/X01')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="copy-problem-link"' in page
    assert 'Sao chép link' in page
    assert 'navigator.clipboard' in page
    assert 'window.location.href' in page

def test_problem_detail_shows_private_recent_submission_panel(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems/X01')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="recent-submissions-panel"' in page
    assert 'id="recent-submissions-list"' in page
    assert 'Lần nộp gần đây' in page
    assert '/api/submissions?' in page
    assert client.get('/api/submissions?scope=mine&problem_id=X01&limit=8').status_code == 401


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


def test_mobile_navigation_toggle_is_accessible_and_keyboard_operable(tmp_path):
    client = setup(tmp_path)
    page = client.get('/').get_data(as_text=True)

    assert 'id="mobile-nav-toggle"' in page
    assert 'aria-controls="main-navigation"' in page
    assert 'aria-expanded="false"' in page
    assert 'id="main-navigation"' in page
    assert 'trantu-mobile-nav-v1' in page
    assert 'html.theme-dark .mobile-nav-toggle' in page

    script = client.get('/static/app.js').get_data(as_text=True)
    assert 'MOBILE NAVIGATION' in script
    assert "event.key === 'Escape'" in script
    assert "oj-language-changed" in script


def test_internal_problem_translation_uses_authored_local_catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'translate_to_english', lambda value: None)
    client = setup(tmp_path)
    catalogue = tmp_path / 'problem_translations.en.json'
    catalogue.write_text(json.dumps({
        'X01': {
            'title': 'Sum of Two Numbers',
            'statement': 'Given two integers a and b. Print their sum.',
            'input_format': 'One line contains a and b.',
            'output_format': 'Print a + b.',
            'category': 'Fundamentals',
            'difficulty': 'Easy',
            'subtasks': [{
                'id': 'all',
                'name': 'All test cases',
                'constraints': '1 <= a, b <= 100'
            }]
        }
    }), encoding='utf-8')
    client.application.config['PROBLEM_TRANSLATIONS_PATH'] = str(catalogue)

    response = client.get('/api/problems/X01/translation')
    assert response.status_code == 200
    assert response.json['translation_available'] is True
    assert response.json['translation_source'] == 'internal'
    assert response.json['title'] == 'Sum of Two Numbers'
    assert response.json['statement'].startswith('Given two integers')
    assert response.json['subtasks'][0]['name'] == 'All test cases'


def test_internal_problem_translation_falls_back_without_external_service(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'translate_to_english', lambda value: None)
    client = setup(tmp_path)
    response = client.get('/api/problems/X01/translation')
    assert response.status_code == 200
    assert response.json['translation_available'] is False
    assert response.json['translation_source'] == 'internal'
    assert response.json['title'] == 'English translation unavailable'
    assert response.json['statement'] == (
        'The English statement for this problem has not been added yet.'
    )
    assert response.json['input_format'] == (
        'The English input description is not available yet.'
    )
    assert response.json['output_format'] == (
        'The English output description is not available yet.'
    )
    assert 'Cho hai số nguyên' not in response.get_data(as_text=True)


def test_problem_page_no_longer_displays_external_translation_failure(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems/X01')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'Automatic translation is temporarily unavailable' not in page
    assert '/api/problems/X01/translation' in page
    assert 'translationUnavailable' in page

    app_source = client.application.view_functions['translate_problem_page'].__code__.co_consts
    assert not any('translate.googleapis.com' in str(item) for item in app_source)
    assert not any('mymemory.translated.net' in str(item) for item in app_source)


def test_every_jinja_template_compiles(tmp_path):
    client = setup(tmp_path)
    template_names = sorted(client.application.jinja_env.list_templates())
    assert template_names

    for template_name in template_names:
        client.application.jinja_env.get_template(template_name)


def test_public_pages_and_contest_api_smoke(tmp_path):
    client = setup(tmp_path)

    for path in (
        '/',
        '/problems',
        '/library',
        '/contests',
        '/leaderboard',
        '/about',
        '/contests/999999'
    ):
        response = client.get(path)
        assert response.status_code == 200, (
            f'{path} returned HTTP {response.status_code}'
        )

    contests = client.get('/api/contests')
    assert contests.status_code == 200
    assert contests.is_json
    assert contests.get_json() == []


def test_library_custom_problem_translation_uses_contest_context(tmp_path):
    client = setup(tmp_path)
    app = client.application
    now = datetime.now()
    start = (now - timedelta(hours=1)).isoformat(timespec='seconds')
    end = (now + timedelta(hours=1)).isoformat(timespec='seconds')

    with connect(app.config['DATABASE_PATH']) as db:
        contest_id = db.execute(
            '''INSERT INTO contests
               (title, description, start_time, end_time, is_visible)
               VALUES (?, ?, ?, ?, 1)''',
            ('Translation regression', '', start, end)
        ).lastrowid
        db.execute(
            '''INSERT INTO contest_problems
               (contest_id, problem_id, position, total_score)
               VALUES (?, ?, 0, 100)''',
            (contest_id, 'CUSTOM01')
        )
        db.execute(
            '''INSERT INTO contest_custom_problems
               (contest_id, problem_id, title, statement, input_desc,
                output_desc, subtasks_json, total_score, sample_input,
                sample_output)
               VALUES (?, ?, ?, ?, ?, ?, ?, 100, ?, ?)''',
            (
                contest_id, 'CUSTOM01', 'Bài tự tạo', 'Cho số n.',
                'Một số nguyên n.', 'In n.', json.dumps([{
                    'id': 'all', 'name': 'Toàn bộ', 'score': 100,
                    'constraints': '1 <= n <= 10'
                }]), '5', '5'
            )
        )

    catalogue = tmp_path / 'problem_translations.en.json'
    catalogue.write_text(json.dumps({
        'CUSTOM01': {
            'title': 'Custom Problem',
            'statement': 'Given an integer n.',
            'input_format': 'One integer n.',
            'output_format': 'Print n.',
            'subtasks': [{
                'id': 'all',
                'name': 'All tests',
                'constraints': '1 <= n <= 10'
            }]
        }
    }), encoding='utf-8')
    app.config['PROBLEM_TRANSLATIONS_PATH'] = str(catalogue)

    response = client.get(
        f'/api/problems/CUSTOM01/translation?contest_id={contest_id}'
    )
    assert response.status_code == 200
    assert response.json['translation_available'] is True
    assert response.json['title'] == 'Custom Problem'
    assert response.json['statement'] == 'Given an integer n.'
    assert response.json['subtasks'][0]['name'] == 'All tests'

    page = client.get(f'/library/{contest_id}/problem/CUSTOM01')
    assert page.status_code == 200
    assert (
        f'/api/problems/CUSTOM01/translation?contest_id={contest_id}'
        in page.get_data(as_text=True)
    )


def test_library_translation_does_not_expose_hidden_contest(tmp_path):
    client = setup(tmp_path)
    app = client.application
    now = datetime.now()
    with connect(app.config['DATABASE_PATH']) as db:
        contest_id = db.execute(
            '''INSERT INTO contests
               (title, description, start_time, end_time, is_visible)
               VALUES (?, ?, ?, ?, 0)''',
            (
                'Hidden contest', '',
                (now - timedelta(hours=1)).isoformat(timespec='seconds'),
                (now + timedelta(hours=1)).isoformat(timespec='seconds')
            )
        ).lastrowid
        db.execute(
            '''INSERT INTO contest_problems
               (contest_id, problem_id, position, total_score)
               VALUES (?, ?, 0, 100)''',
            (contest_id, 'HIDDEN01')
        )
        db.execute(
            '''INSERT INTO contest_custom_problems
               (contest_id, problem_id, title, statement)
               VALUES (?, ?, ?, ?)''',
            (contest_id, 'HIDDEN01', 'Hidden', 'Hidden statement')
        )

    response = client.get(
        f'/api/problems/HIDDEN01/translation?contest_id={contest_id}'
    )
    assert response.status_code == 404



def test_problemset_has_tag_filter_and_tag_search_support(tmp_path):
    client = setup(tmp_path)
    page = client.get('/problems')
    assert page.status_code == 200
    assert 'id="filter-tag"' in page.get_data(as_text=True)
    script = client.get('/static/app.js').get_data(as_text=True)
    assert "const tag = document.querySelector('#filter-tag')" in script
    assert 'problemTags.includes(tag)' in script
    assert '...problemTags' in script
    assert 'searchableText' in script


def test_submit_editor_supports_local_autosave_and_keyboard_shortcuts(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'editoruser')
    page = client.get('/problems/X01/submit')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'id="draft-status"' in html
    assert 'trantuoj:draft:' in html
    assert "event.key==='Tab'" in html
    assert "event.key.toLowerCase()==='s'" in html
    assert "event.key==='Enter'" in html


def test_my_analytics_reports_current_and_longest_activity_streak(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'streakuser')
    app = client.application
    today = datetime.now().date()
    active = [today - timedelta(days=offset) for offset in (0, 1, 2, 4, 5)]
    with connect(app.config['DATABASE_PATH']) as db:
        user = db.execute('SELECT id FROM users WHERE username=?', ('streakuser',)).fetchone()
        for day in active:
            db.execute(
                '''INSERT INTO submissions
                   (user_id, problem_id, language_id, source_code, verdict,
                    score, max_score, created_at)
                   VALUES (?, 'X01', 54, 'int main(){}', 'Wrong Answer', 0, 100, ?)''',
                (user['id'], day.isoformat() + 'T12:00:00')
            )
    response = client.get('/api/my-analytics')
    assert response.status_code == 200
    assert response.json['current_streak'] == 3
    assert response.json['longest_streak'] == 3
    assert response.json['active_days'] == 5



def test_contest_page_has_live_countdown_and_leaderboard_auto_refresh(tmp_path):
    client = setup(tmp_path)
    contest_page = client.get('/contests/1')
    assert contest_page.status_code == 200
    html = contest_page.get_data(as_text=True)
    assert 'id="contest-countdown"' in html
    assert 'updateContestCountdown' in html
    section = client.get('/contests/1/leaderboard')
    assert section.status_code == 200
    source = section.get_data(as_text=True)
    assert 'refreshLeaderboard' in source
    assert 'setInterval(refreshLeaderboard, 15000)' in source



def test_hidden_contest_apis_and_admin_apis_enforce_permissions(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'boundaryuser')
    app = client.application
    now = datetime.now()
    with connect(app.config['DATABASE_PATH']) as db:
        contest_id = db.execute(
            '''INSERT INTO contests
               (title, description, start_time, end_time, is_visible)
               VALUES (?, ?, ?, ?, 0)''',
            (
                'Private boundary contest', '',
                (now - timedelta(hours=1)).isoformat(timespec='seconds'),
                (now + timedelta(hours=1)).isoformat(timespec='seconds')
            )
        ).lastrowid

    hidden_paths = [
        f'/api/contests/{contest_id}',
        f'/api/contests/{contest_id}/stats',
        f'/api/contests/{contest_id}/leaderboard',
        f'/api/contests/{contest_id}/my-progress',
        f'/api/contests/{contest_id}/submissions',
        f'/library/{contest_id}/problem/PRIVATE01'
    ]
    for path in hidden_paths:
        response = client.get(path)
        assert response.status_code == 404, f'{path}: {response.status_code}'

    admin_paths = [
        ('GET', '/api/admin/users'),
        ('GET', '/api/admin/statistics'),
        ('GET', '/api/admin/submissions'),
        ('GET', '/api/admin/contests'),
        ('GET', f'/api/admin/contests/{contest_id}/full'),
        ('GET', '/api/admin/submissions/1/source')
    ]
    for method, path in admin_paths:
        response = client.open(path, method=method)
        assert response.status_code == 403, f'{method} {path}: {response.status_code}'


def test_submission_code_and_status_are_private_to_owner(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'submissionowner')
    app = client.application
    with connect(app.config['DATABASE_PATH']) as db:
        owner = db.execute(
            'SELECT id FROM users WHERE username=?', ('submissionowner',)
        ).fetchone()
        submission_id = db.execute(
            '''INSERT INTO submissions
               (user_id, problem_id, language_id, source_code, verdict,
                score, max_score, details_json)
               VALUES (?, 'X01', 54, 'int main(){return 0;}', 'Wrong Answer',
                       0, 100, '[]')''',
            (owner['id'],)
        ).lastrowid

    client.post('/api/logout')
    register_and_login(client, 'submissionviewer')
    for suffix in ('code', 'status'):
        response = client.get(f'/api/submissions/{submission_id}/{suffix}')
        assert response.status_code == 403



def test_submit_editor_has_safe_drafts_and_productivity_shortcuts(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems/X01/submit')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'id="copy-source"' in page
    assert 'id="restore-starter"' in page
    assert 'id="editor-stats"' in page
    assert "beforeunload" in page
    assert "event.key==='Enter'" in page
    assert "event.shiftKey" in page
    assert "event.key==='/'" in page



def test_private_api_requires_authentication_and_submit_rejects_bad_payloads(tmp_path):
    client = setup(tmp_path)

    private_gets = [
        '/api/saved-problems',
        '/api/my-progress',
        '/api/my-analytics',
        '/api/my-library-progress',
        '/api/submissions/1/code',
        '/api/submissions/1/status',
        '/api/contests/1/my-progress',
        '/api/contests/1/submissions',
    ]
    for path in private_gets:
        response = client.get(path)
        assert response.status_code == 401, f'{path}: {response.status_code}'

    for path in (
        '/api/admin/users',
        '/api/admin/statistics',
        '/api/admin/submissions',
        '/api/admin/contests',
        '/api/admin/problems',
    ):
        response = client.get(path)
        assert response.status_code == 403, f'{path}: {response.status_code}'

    assert client.post('/api/submit', json={
        'problem_id': 'X01', 'source_code': 'int main(){}'
    }).status_code == 401
    assert client.post('/api/contests/1/submit', json={
        'problem_id': 'X01', 'source_code': 'int main(){}'
    }).status_code == 401

    register_and_login(client, 'payloadboundary')
    malformed = client.post(
        '/api/submit', data='{not-json', content_type='application/json'
    )
    assert malformed.status_code == 404

    empty = client.post('/api/submit', json={
        'problem_id': 'X01', 'source_code': '   '
    })
    assert empty.status_code == 400

    oversized = client.post('/api/submit', json={
        'problem_id': 'X01', 'source_code': 'x' * 100001
    })
    assert oversized.status_code == 400

    invalid_language = client.post('/api/submit', json={
        'problem_id': 'X01', 'source_code': 'int main(){}',
        'language_id': 'not-a-number'
    })
    assert invalid_language.status_code == 400


def test_contest_submission_enforces_membership_and_time_boundaries(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'contestboundary')
    app = client.application
    now = datetime.now()
    future_start = (now + timedelta(hours=1)).isoformat(timespec='seconds')
    future_end = (now + timedelta(hours=2)).isoformat(timespec='seconds')
    with connect(app.config['DATABASE_PATH']) as db:
        contest_id = db.execute(
            '''INSERT INTO contests
               (title, description, start_time, end_time, is_visible)
               VALUES (?, ?, ?, ?, 1)''',
            ('Boundary contest', '', future_start, future_end)
        ).lastrowid
        db.execute(
            '''INSERT INTO contest_problems
               (contest_id, problem_id, position, total_score)
               VALUES (?, 'X01', 0, 100)''',
            (contest_id,)
        )

    payload = {
        'problem_id': 'X01',
        'source_code': 'int main(){return 0;}',
        'language_id': 54
    }
    endpoint = f'/api/contests/{contest_id}/submit'
    before_start = client.post(endpoint, json=payload)
    assert before_start.status_code == 403
    assert 'chưa bắt đầu' in before_start.json['error'].lower()

    with connect(app.config['DATABASE_PATH']) as db:
        db.execute(
            'UPDATE contests SET start_time=?, end_time=? WHERE id=?',
            (
                (now - timedelta(hours=2)).isoformat(timespec='seconds'),
                (now - timedelta(hours=1)).isoformat(timespec='seconds'),
                contest_id
            )
        )
    after_end = client.post(endpoint, json=payload)
    assert after_end.status_code == 403
    assert 'đã kết thúc' in after_end.json['error'].lower()

    with connect(app.config['DATABASE_PATH']) as db:
        db.execute(
            'UPDATE contests SET start_time=?, end_time=? WHERE id=?',
            (
                (now - timedelta(hours=1)).isoformat(timespec='seconds'),
                (now + timedelta(hours=1)).isoformat(timespec='seconds'),
                contest_id
            )
        )
    not_member = client.post(
        endpoint, json={**payload, 'problem_id': 'NOT_IN_CONTEST'}
    )
    assert not_member.status_code == 403
    assert 'không thuộc cuộc thi' in not_member.json['error'].lower()



def test_english_problem_page_never_restores_vietnamese_on_translation_failure(tmp_path):
    client = setup(tmp_path)
    page = client.get('/problems/X01').get_data(as_text=True)

    assert 'Vietnamese content is hidden in English mode.' in page
    assert 'The English version could not be loaded. Vietnamese content is hidden in English mode.' in page
    assert 'setText("problem-title", original.title)' not in page


def test_incomplete_translation_never_falls_back_to_vietnamese_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, 'translate_to_english', lambda value: None)
    client = setup(tmp_path)
    catalogue = tmp_path / 'problem_translations.en.json'
    catalogue.write_text(json.dumps({
        'X01': {
            'title': 'English title',
            'statement': 'English statement only'
        }
    }), encoding='utf-8')
    client.application.config['PROBLEM_TRANSLATIONS_PATH'] = str(catalogue)

    response = client.get('/api/problems/X01/translation')
    assert response.status_code == 200
    assert response.json['translation_available'] is False
    assert response.json['title'] == 'English title'
    assert response.json['statement'] == 'English statement only'
    assert response.json['input_format'] == (
        'The English input description is not available yet.'
    )
    assert response.json['output_format'] == (
        'The English output description is not available yet.'
    )
    assert 'Một dòng' not in response.get_data(as_text=True)


def test_problemset_page_exposes_partial_score_status_filter(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems')
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert 'value="partial">Đạt một phần' in page
    assert 'value="attempted"' in page


def test_problemset_search_supports_accent_insensitive_multiword_matching():
    from pathlib import Path

    source = Path('static/app.js').read_text(encoding='utf-8')
    assert ".normalize('NFD')" in source
    assert "replace(/đ/g, 'd')" in source
    assert "queryTokens.every(token => searchableText.includes(token))" in source
    assert "p.short_description" in source
    assert "progress?.best_score" in source


def test_submit_editor_uses_real_newlines_for_multiline_editing(tmp_path):
    client = setup(tmp_path)
    page = client.get('/problems/X01/submit')
    assert page.status_code == 200
    html = page.get_data(as_text=True)

    # JavaScript must receive newline and whitespace escapes, not literal
    # backslash-plus-letter sequences, for line counting and indentation.
    assert r"value.split('\n')" in html
    assert r"value.lastIndexOf('\n'" in html
    assert r"value.indexOf('\n'" in html
    assert r"setRangeText('\n'" in html
    assert r"before.match(/^\s*/)" in html
    assert r"selected.split('\n')" in html
    assert r"join('\n')" in html



def test_submission_status_reports_live_test_progress_for_owner(tmp_path):
    client = setup(tmp_path)
    register_and_login(client, 'progressowner')
    app = client.application
    problem_snapshot = {
        'id': 'X01',
        'subtasks': [{
            'id': 'all',
            'name': 'All tests',
            'tests': [
                {'input': 'hidden 1', 'output': 'hidden 1'},
                {'input': 'hidden 2', 'output': 'hidden 2'},
                {'input': 'hidden 3', 'output': 'hidden 3'}
            ]
        }]
    }
    partial_details = [{
        'subtask': 'all',
        'name': 'All tests',
        'score': 10,
        'max_score': 30,
        'tests': [
            {'test': 1, 'status': 'Accepted', 'score': 10, 'max_score': 10},
            {'test': 2, 'status': 'Processing', 'score': 0, 'max_score': 10},
            {'test': 3, 'status': 'Processing', 'score': 0, 'max_score': 10}
        ]
    }]
    with connect(app.config['DATABASE_PATH']) as db:
        owner = db.execute(
            'SELECT id FROM users WHERE username=?', ('progressowner',)
        ).fetchone()
        submission_id = db.execute(
            '''INSERT INTO submissions
               (user_id, problem_id, language_id, source_code, verdict,
                score, max_score, details_json, problem_json)
               VALUES (?, 'X01', 54, 'int main(){}', 'Processing',
                       10, 30, ?, ?)''',
            (
                owner['id'],
                json.dumps(partial_details),
                json.dumps(problem_snapshot)
            )
        ).lastrowid

    response = client.get(f'/api/submissions/{submission_id}/status')
    assert response.status_code == 200
    data = response.get_json()
    assert data['progress_completed'] == 1
    assert data['progress_total'] == 3
    assert data['progress_percent'] == 33
    assert data['progress_phase'] == 'judging'
    assert 'hidden 1' not in response.get_data(as_text=True)


def test_submit_page_has_run_code_workspace(tmp_path):
    client = setup(tmp_path)
    response = client.get('/problems/X01/submit')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="run-code"' in html
    assert 'id="run-input"' in html
    assert 'id="run-output"' in html
    assert '1 2' in html


def test_run_code_requires_login_and_validates_payload(tmp_path):
    client = setup(tmp_path)
    assert client.post('/api/run', json={}).status_code == 401

    register_and_login(client, 'samplerunner')
    response = client.post('/api/run', json={
        'problem_id': 'X01',
        'source_code': 'int main() {}',
        'language_id': 999,
        'stdin': ''
    })
    assert response.status_code == 400
    assert 'C++ và Python 3' in response.json['error']

    response = client.post('/api/run', json={
        'problem_id': 'X01',
        'source_code': 'int main() {}',
        'language_id': 54,
        'stdin': 'x' * 50001
    })
    assert response.status_code == 400


def test_run_code_uses_judge0_without_creating_submission(tmp_path, monkeypatch):
    client = setup(tmp_path)
    register_and_login(client, 'samplerunner2')
    captured = {}

    class FakeJudge0:
        def __init__(self, base_url, api_key):
            captured['base_url'] = base_url

        def run(self, source, language_id, stdin, expected, **kwargs):
            captured.update({
                'source': source,
                'language_id': language_id,
                'stdin': stdin,
                'expected': expected,
                'kwargs': kwargs
            })
            return {
                'status': 'Accepted',
                'stdout': '3\\n',
                'stderr': '',
                'compile_output': '',
                'message': '',
                'time': 0.01,
                'memory': 1024
            }

    monkeypatch.setattr(app_module, 'Judge0', FakeJudge0)
    response = client.post('/api/run', json={
        'problem_id': 'X01',
        'source_code': 'int main(){return 0;}',
        'language_id': 54,
        'stdin': '1 2\\n'
    })

    assert response.status_code == 200
    assert response.json['stdout'] == '3\\n'
    assert captured['expected'] is None
    assert captured['stdin'] == '1 2\\n'
    assert captured['kwargs']['max_wait_seconds'] == 20

    with connect(client.application.config['DATABASE_PATH']) as db:
        count = db.execute('SELECT COUNT(*) AS total FROM submissions').fetchone()['total']
    assert count == 0
