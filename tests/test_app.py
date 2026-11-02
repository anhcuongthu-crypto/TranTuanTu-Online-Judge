import json
from app import create_app


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
    assert c.get('/health').json['problem_count'] == 1
    assert c.get('/api/problems').json[0]['id'] == 'X01'
    detail = c.get('/api/problems/X01').json
    assert detail['sample_input'] == '1 2\n'
    assert detail['sample_output'] == '3\n'
    assert detail['explanation']
    assert detail['subtasks'][0]['score'] == 100


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

def test_home_problemset_library_and_brand_assets_render(tmp_path):
    c = setup(tmp_path)

    home = c.get('/')
    assert home.status_code == 200
    assert b'class="hero-art"' in home.data
    assert b'og-cover.svg' in home.data
    assert b'favicon.svg' in home.data

    assert c.get('/problems').status_code == 200
    assert c.get('/library').status_code == 200
    assert c.get('/contests').status_code == 200

    assert c.get('/static/favicon.svg').status_code == 200
    assert c.get('/static/og-cover.svg').status_code == 200
