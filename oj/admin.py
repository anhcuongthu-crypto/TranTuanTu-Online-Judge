
"""Administrator-only account and submission management routes."""

from flask import jsonify


def register_admin_routes(app, connect, current_user, database_path):

    def require_admin():
        user = current_user()
        if not user or not user['is_admin']:
            return None
        return user

    @app.get('/api/admin/users')
    def admin_users():
        user = require_admin()
        if not user:
            return jsonify(error='Chỉ admin.'), 403

        with connect(database_path) as db:
            rows = db.execute(
                '''
                SELECT id, username, approved, created_at
                FROM users
                WHERE is_admin = 0
                ORDER BY approved ASC, id ASC
                '''
            ).fetchall()

        return jsonify([dict(row) for row in rows])

    @app.post('/api/admin/users/<int:user_id>/approve')
    def admin_approve_user(user_id):
        user = require_admin()
        if not user:
            return jsonify(error='Chỉ admin.'), 403

        with connect(database_path) as db:
            cur = db.execute(
                '''
                UPDATE users
                SET approved = 1
                WHERE id = ? AND is_admin = 0 AND approved = 0
                ''',
                (user_id,)
            )

            if cur.rowcount != 1:
                return jsonify(
                    error='Không tìm thấy tài khoản chờ duyệt.'
                ), 404

        return jsonify(
            ok=True,
            user_id=user_id,
            approved=True
        )

    @app.post('/api/admin/users/<int:user_id>/reject')
    def admin_reject_user(user_id):
        user = require_admin()
        if not user:
            return jsonify(error='Chỉ admin.'), 403

        with connect(database_path) as db:
            cur = db.execute(
                '''
                DELETE FROM users
                WHERE id = ? AND is_admin = 0 AND approved = 0
                ''',
                (user_id,)
            )

            if cur.rowcount != 1:
                return jsonify(
                    error='Không tìm thấy tài khoản chờ duyệt.'
                ), 404

        return jsonify(
            ok=True,
            user_id=user_id,
            rejected=True
        )

    # DANH SÁCH BÀI NỘP
    @app.get('/api/admin/submissions')
    def admin_submissions():
        user = require_admin()
        if not user:
            return jsonify(error='Chỉ admin.'), 403

        with connect(database_path) as db:
            rows = db.execute(
                '''
                SELECT
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
                JOIN users u ON u.id = s.user_id
                ORDER BY s.id DESC
                LIMIT 200
                '''
            ).fetchall()

        return jsonify([dict(row) for row in rows])

    # XEM MÃ NGUỒN MỘT BÀI NỘP
    @app.get('/api/admin/submissions/<int:submission_id>/source')
    def admin_submission_source(submission_id):
        user = require_admin()
        if not user:
            return jsonify(error='Chỉ admin.'), 403

        with connect(database_path) as db:
            row = db.execute(
                '''
                SELECT
                    s.id,
                    u.username,
                    s.problem_id,
                    s.language_id,
                    s.source_code,
                    s.created_at
                FROM submissions s
                JOIN users u ON u.id = s.user_id
                WHERE s.id = ?
                ''',
                (submission_id,)
            ).fetchone()

        if not row:
            return jsonify(error='Không tìm thấy bài nộp.'), 404

        return jsonify(dict(row))
