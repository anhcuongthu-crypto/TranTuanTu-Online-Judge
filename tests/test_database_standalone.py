"""Tests for SQLite schema/migrations that do not require Flask."""
from oj.database import connect, init_db, _qmark_to_pyformat


def test_new_database_has_approval_and_unique_username(tmp_path):
    path = tmp_path / 'db.sqlite3'
    init_db(path)
    with connect(path) as db:
        cols = {r['name'] for r in db.execute('PRAGMA table_info(users)')}
        assert {'username', 'password_hash', 'is_admin', 'approved'} <= cols
        db.execute("INSERT INTO users(username,password_hash,approved) VALUES('student','hash',0)")
        try:
            db.execute("INSERT INTO users(username,password_hash,approved) VALUES('student','hash',0)")
        except Exception:
            pass
        else:
            raise AssertionError('Duplicate username was accepted')


def test_existing_database_migrates_approval_column(tmp_path):
    path = tmp_path / 'old.sqlite3'
    with connect(path) as db:
        db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    init_db(path)
    with connect(path) as db:
        cols = {r['name'] for r in db.execute('PRAGMA table_info(users)')}
        assert 'approved' in cols
        assert db.execute('SELECT approved FROM users').fetchall() == []


def test_init_db_is_idempotent_and_preserves_existing_contest(tmp_path):
    path = tmp_path / 'persistent.sqlite3'
    init_db(path)
    with connect(path) as db:
        user = db.execute(
            "INSERT INTO users(username, password_hash, approved) VALUES (?, ?, 1)",
            ('student_one', 'hash')
        )
        user_id = user.lastrowid
        contest = db.execute(
            """INSERT INTO contests(title, description, start_time, end_time, is_visible, created_by)
               VALUES (?, ?, ?, ?, 1, ?)""",
            ('Contest kiểm thử', '', '2026-10-26T08:00', '2026-10-26T10:00', user_id)
        )
        contest_id = contest.lastrowid

    # Re-running migrations must not drop any user or contest records.
    init_db(path)
    with connect(path) as db:
        assert db.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()['username'] == 'student_one'
        assert db.execute('SELECT title FROM contests WHERE id=?', (contest_id,)).fetchone()['title'] == 'Contest kiểm thử'


def test_postgres_placeholder_translation_does_not_change_quoted_question_marks():
    sql = "SELECT '?' AS literal WHERE id=? -- ? is only a comment\n"
    assert _qmark_to_pyformat(sql) == "SELECT '?' AS literal WHERE id=%s -- ? is only a comment\n"
