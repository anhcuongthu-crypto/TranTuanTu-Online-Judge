"""Database helpers supporting SQLite locally and PostgreSQL on Render."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

_POSTGRES_PREFIXES = (
    "postgres://",
    "postgresql://",
    "postgresql+psycopg://"
)

_AUTO_ID_TABLES = {
    "users",
    "submissions",
    "contests",
    "contest_custom_problems",
    "problem_history"
}

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

try:
    import psycopg
    from psycopg import IntegrityError as _PsycopgIntegrityError
except ImportError:
    psycopg = None
    _PsycopgIntegrityError = None


DB_INTEGRITY_ERRORS = (
    sqlite3.IntegrityError,
) + ((_PsycopgIntegrityError,) if _PsycopgIntegrityError else ())


def is_postgres_path(path: Any) -> bool:
    return str(path or "").strip().lower().startswith(_POSTGRES_PREFIXES)


def _normalize_dsn(path: Any) -> str:
    dsn = str(path).strip()

    if dsn.startswith("postgres://"):
        return "postgresql://" + dsn[len("postgres://"):]

    if dsn.startswith("postgresql+psycopg://"):
        return "postgresql://" + dsn[len("postgresql+psycopg://"):]

    return dsn


class _CompatRow(dict):
    """Dictionary-style row with SQLite-compatible integer indexing."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]

        return super().__getitem__(key)


def _postgres_row_factory(cursor):
    columns = [
        column.name for column in cursor.description
    ] if cursor.description else []

    def make_row(values):
        return _CompatRow(zip(columns, values))

    return make_row


def _qmark_to_pyformat(sql: str) -> str:
    """Translate ? placeholders without altering literals or SQL comments."""

    out = []
    i = 0
    state = "normal"

    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if state == "single":
            out.append(ch)

            if ch == "'":
                if nxt == "'":
                    out.append(nxt)
                    i += 1
                else:
                    state = "normal"

        elif state == "double":
            out.append(ch)

            if ch == '"':
                if nxt == '"':
                    out.append(nxt)
                    i += 1
                else:
                    state = "normal"

        elif state == "line_comment":
            out.append(ch)

            if ch == "\n":
                state = "normal"

        elif state == "block_comment":
            out.append(ch)

            if ch == "*" and nxt == "/":
                out.append(nxt)
                i += 1
                state = "normal"

        elif ch == "'":
            out.append(ch)
            state = "single"

        elif ch == '"':
            out.append(ch)
            state = "double"

        elif ch == "-" and nxt == "-":
            out.extend((ch, nxt))
            i += 1
            state = "line_comment"

        elif ch == "/" and nxt == "*":
            out.extend((ch, nxt))
            i += 1
            state = "block_comment"

        elif ch == "?":
            out.append("%s")

        else:
            out.append(ch)

        i += 1

    return "".join(out)


class _CursorAdapter:
    def __init__(self, cursor, lastrowid=None, first_row=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self._first_row = first_row

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        if self._first_row is not None:
            row, self._first_row = self._first_row, None
            return row

        return self._cursor.fetchone()

    def fetchall(self):
        rows = self._cursor.fetchall()

        if self._first_row is not None:
            rows.insert(0, self._first_row)
            self._first_row = None

        return rows

    def fetchmany(self, size=None):
        if self._first_row is None:
            if size is None:
                return self._cursor.fetchmany()

            return self._cursor.fetchmany(size)

        first, self._first_row = self._first_row, None
        rest = self._cursor.fetchmany(max(0, (size or 1) - 1))

        return [first, *rest]


class _PostgresConnection:
    def __init__(self, raw_connection):
        self._connection = raw_connection

    def execute(self, query, parameters=None):
        sql = _qmark_to_pyformat(query)

        add_returning = False

        match = re.match(
            r"\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)",
            sql,
            re.I
        )

        if (
            match
            and match.group(1).lower() in _AUTO_ID_TABLES
            and not re.search(r"\bRETURNING\b", sql, re.I)
        ):
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
            add_returning = True

        cursor = self._connection.cursor()

        if parameters is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, parameters)

        if add_returning:
            row = cursor.fetchone()

            return _CursorAdapter(
                cursor,
                lastrowid=(row["id"] if row else None),
                first_row=row
            )

        return _CursorAdapter(cursor)

    def executemany(self, query, parameters):
        cursor = self._connection.cursor()

        cursor.executemany(
            _qmark_to_pyformat(query),
            parameters
        )

        return _CursorAdapter(cursor)

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()

        return False

    def close(self):
        self._connection.close()


def connect(path):
    """Open SQLite for file paths and psycopg for PostgreSQL DSNs."""

    if is_postgres_path(path):
        if psycopg is None:
            raise RuntimeError(
                "DATABASE_URL là PostgreSQL nhưng thiếu psycopg. "
                "Hãy cài các gói trong requirements.txt."
            )

        raw = psycopg.connect(
            _normalize_dsn(path),
            row_factory=_postgres_row_factory,
            connect_timeout=15
        )

        return _PostgresConnection(raw)

    sqlite_path = str(path)

    if sqlite_path != ":memory:":
        Path(sqlite_path).parent.mkdir(
            parents=True,
            exist_ok=True
        )

    db = sqlite3.connect(
        sqlite_path,
        timeout=20
    )

    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")

    return db


def get_table_columns(path, table_name):
    if not _IDENTIFIER_RE.fullmatch(str(table_name)):
        raise ValueError("Tên bảng không hợp lệ.")

    if is_postgres_path(path):
        with connect(path) as db:
            rows = db.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                AND table_name = ?
                """,
                (table_name,)
            ).fetchall()

        return {
            row["column_name"] for row in rows
        }

    with connect(path) as db:
        return {
            row["name"]
            for row in db.execute(
                f"PRAGMA table_info({table_name})"
            ).fetchall()
        }


def ensure_column(path, table_name, column_name, definition):
    """Add a missing column in-place; never drops or replaces a table."""

    if (
        not _IDENTIFIER_RE.fullmatch(str(table_name))
        or not _IDENTIFIER_RE.fullmatch(str(column_name))
    ):
        raise ValueError("Tên bảng hoặc cột không hợp lệ.")

    if column_name not in get_table_columns(path, table_name):
        with connect(path) as db:
            if column_name not in get_table_columns(path, table_name):
                db.execute(
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {definition}"
                )


def _init_sqlite(path):
    with connect(path) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            approved INTEGER NOT NULL DEFAULT 0,
            avatar_color TEXT NOT NULL DEFAULT '#7c3aed',
            bio TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS contests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_visible INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS submissions(
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            problem_id TEXT NOT NULL,
            language_id INTEGER NOT NULL,
            source_code TEXT NOT NULL,
            verdict TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0,
            max_score REAL NOT NULL DEFAULT 100,
            details_json TEXT NOT NULL DEFAULT '[]',
            contest_id INTEGER REFERENCES contests(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS solves(
            user_id INTEGER NOT NULL REFERENCES users(id),
            problem_id TEXT NOT NULL,
            best_score REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, problem_id)
        );

        CREATE TABLE IF NOT EXISTS contest_problems(
            contest_id INTEGER NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
            problem_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(contest_id, problem_id)
        );

        CREATE TABLE IF NOT EXISTS contest_custom_problems(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id INTEGER NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
            problem_id TEXT NOT NULL,
            title TEXT NOT NULL,
            statement TEXT NOT NULL DEFAULT '',
            input_desc TEXT NOT NULL DEFAULT '',
            output_desc TEXT NOT NULL DEFAULT '',
            subtasks_json TEXT NOT NULL DEFAULT '[]',
            total_score REAL NOT NULL DEFAULT 10,
            time_limit REAL NOT NULL DEFAULT 1,
            memory_limit INTEGER NOT NULL DEFAULT 256000,
            sample_input TEXT NOT NULL DEFAULT '',
            sample_output TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(contest_id, problem_id)
        );

        CREATE TABLE IF NOT EXISTS problem_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            removed_json TEXT NOT NULL DEFAULT '[]',
            before_count INTEGER NOT NULL DEFAULT 0,
            after_count INTEGER NOT NULL DEFAULT 0,
            removed_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_submissions_user
        ON submissions(user_id, id DESC);

        CREATE INDEX IF NOT EXISTS idx_submissions_problem
        ON submissions(problem_id);
        """)


def _init_postgres(path):
    schema = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            approved INTEGER NOT NULL DEFAULT 0,
            avatar_color TEXT NOT NULL DEFAULT '#7c3aed',
            bio TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS contests (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            is_visible INTEGER NOT NULL DEFAULT 1,
            created_by BIGINT REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS submissions (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id),
            problem_id TEXT NOT NULL,
            language_id INTEGER NOT NULL,
            source_code TEXT NOT NULL,
            verdict TEXT NOT NULL,
            score DOUBLE NOT NULL DEFAULT 0,
            max_score DOUBLE NOT NULL DEFAULT 100,
            details_json TEXT NOT NULL DEFAULT '[]',
            contest_id BIGINT REFERENCES contests(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS solves (
            user_id BIGINT NOT NULL REFERENCES users(id),
            problem_id TEXT NOT NULL,
            best_score INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id, problem_id)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS contest_problems (
            contest_id BIGINT NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
            problem_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(contest_id, problem_id)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS contest_custom_problems (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            contest_id BIGINT NOT NULL REFERENCES contests(id) ON DELETE CASCADE,
            problem_id TEXT NOT NULL,
            title TEXT NOT NULL,
            statement TEXT NOT NULL DEFAULT '',
            input_desc TEXT NOT NULL DEFAULT '',
            output_desc TEXT NOT NULL DEFAULT '',
            subtasks_json TEXT NOT NULL DEFAULT '[]',
            total_score DOUBLE PRECISION NOT NULL DEFAULT 10,
            time_limit DOUBLE PRECISION NOT NULL DEFAULT 1,
            memory_limit INTEGER NOT NULL DEFAULT 256000,
            sample_input TEXT NOT NULL DEFAULT '',
            sample_output TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text),
            UNIQUE(contest_id, problem_id)
        )
        """,

        """
        CREATE TABLE IF NOT EXISTS problem_history (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            created_at TEXT NOT NULL,
            action TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL,
            removed_json TEXT NOT NULL DEFAULT '[]',
            before_count INTEGER NOT NULL DEFAULT 0,
            after_count INTEGER NOT NULL DEFAULT 0,
            removed_count INTEGER NOT NULL DEFAULT 0
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_submissions_user
        ON submissions(user_id, id DESC)
        """,

        """
        CREATE INDEX IF NOT EXISTS idx_submissions_problem
        ON submissions(problem_id)
        """
    ]

    with connect(path) as db:
        for statement in schema:
            db.execute(statement)


def init_db(path):
    """Create tables and add known legacy columns without deleting data."""

    if is_postgres_path(path):
        _init_postgres(path)
    else:
        _init_sqlite(path)

    migrations = {
        "users": (
            ("approved", "INTEGER NOT NULL DEFAULT 0"),
            ("avatar_color", "TEXT NOT NULL DEFAULT '#7c3aed'"),
            ("bio", "TEXT NOT NULL DEFAULT ''"),
            ("email", "TEXT"),
            ("google_sub", "TEXT"),
        ),

        "submissions": (
            (
                "contest_id",
                "BIGINT REFERENCES contests(id) ON DELETE SET NULL"
                if is_postgres_path(path)
                else "INTEGER REFERENCES contests(id) ON DELETE SET NULL"
            ),
        ),

        "contest_problems": (
            ("total_score", "REAL NOT NULL DEFAULT 10"),
        ),

        "contest_custom_problems": (
            ("sample_input", "TEXT NOT NULL DEFAULT ''"),
            ("sample_output", "TEXT NOT NULL DEFAULT ''"),
        ),

        "problem_history": (
            ("before_count", "INTEGER NOT NULL DEFAULT 0"),
            ("after_count", "INTEGER NOT NULL DEFAULT 0"),
            ("removed_count", "INTEGER NOT NULL DEFAULT 0"),
        ),
    }

    # Bổ sung các cột còn thiếu, giữ nguyên dữ liệu cũ.
    for table, columns in migrations.items():
        for column, definition in columns:
            ensure_column(
                path,
                table,
                column,
                definition
            )

    # Mỗi email và Google ID chỉ thuộc về một tài khoản.
    with connect(path) as db:
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
            ON users(email)
            WHERE email IS NOT NULL AND email <> ''
        """)

        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub_unique
            ON users(google_sub)
            WHERE google_sub IS NOT NULL AND google_sub <> ''
        """)

    # Tạo index sau khi đã bổ sung contest_id.
    with connect(path) as db:
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_submissions_contest
            ON submissions(contest_id, user_id, problem_id)
            """
        )
