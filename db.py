from __future__ import annotations

import json
import os
import random
import sqlite3
import string
from contextlib import contextmanager
from datetime import datetime

from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "database.db")


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_plain TEXT,
                exam_password_hash TEXT NOT NULL,
                exam_password_plain TEXT,
                is_trainer INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS question_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id INTEGER NOT NULL CHECK(block_id IN (2,3,4)),
                question_text TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_option INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS exam_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS exam_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_option INTEGER NOT NULL,
                points INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS exam_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'in_progress'
            );

            CREATE TABLE IF NOT EXISTS exam_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL REFERENCES exam_attempts(id) ON DELETE CASCADE,
                exam_question_id INTEGER NOT NULL REFERENCES exam_questions(id) ON DELETE CASCADE,
                selected_option INTEGER,
                is_standby INTEGER NOT NULL DEFAULT 0,
                UNIQUE(attempt_id, exam_question_id)
            );

            CREATE TABLE IF NOT EXISTS exam_session_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                is_allowed INTEGER NOT NULL DEFAULT 1,
                exam_password_hash TEXT,
                exam_password_plain TEXT,
                UNIQUE(session_id, user_id)
            );
            """
        )
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        names = {col["name"] for col in columns}
        if "exam_password_plain" not in names:
            conn.execute("ALTER TABLE users ADD COLUMN exam_password_plain TEXT")
        if "password_plain" not in names:
            conn.execute("ALTER TABLE users ADD COLUMN password_plain TEXT")
        sp_columns = conn.execute("PRAGMA table_info(exam_session_participants)").fetchall()
        sp_names = {col["name"] for col in sp_columns}
        if "exam_password_hash" not in sp_names:
            conn.execute("ALTER TABLE exam_session_participants ADD COLUMN exam_password_hash TEXT")
        if "exam_password_plain" not in sp_names:
            conn.execute("ALTER TABLE exam_session_participants ADD COLUMN exam_password_plain TEXT")
        missing = conn.execute(
            """
            SELECT id, username
            FROM users
            WHERE is_trainer = 0 AND (exam_password_plain IS NULL OR exam_password_plain = '')
            """
        ).fetchall()
        for row in missing:
            generated = generate_exam_password(row["username"])
            conn.execute(
                """
                UPDATE users
                SET exam_password_plain = ?, exam_password_hash = ?
                WHERE id = ?
                """,
                (generated, generate_password_hash(generated), row["id"]),
            )


def generate_exam_password(username: str) -> str:
    clean = "".join(ch for ch in username.lower() if ch.isalnum())
    tail = "".join(random.choices(string.digits, k=4))
    base = clean[:8] if clean else "utente"
    return f"{base}{tail}"


def seed_demo_data():
    with get_db() as conn:
        users_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if users_count == 0:
            conn.execute(
                """
                INSERT INTO users (username, full_name, password_hash, exam_password_hash, is_trainer)
                VALUES (?, ?, ?, ?, 1)
                """,
                (
                    "trainer",
                    "Formatore Demo",
                    generate_password_hash("trainer123"),
                    generate_password_hash("trainer123"),
                ),
            )
            conn.execute(
                """
                INSERT INTO users (username, full_name, password_hash, exam_password_hash, is_trainer)
                VALUES (?, ?, ?, ?, 0)
                """,
                (
                    "mario.rossi",
                    "Mario Rossi",
                    generate_password_hash("password123"),
                    generate_password_hash("esame123"),
                ),
            )
            conn.execute(
                "UPDATE users SET password_plain = ? WHERE username = ?",
                ("password123", "mario.rossi"),
            )
            conn.execute(
                "UPDATE users SET exam_password_plain = ? WHERE username = ?",
                ("esame123", "mario.rossi"),
            )

        pool_count = conn.execute("SELECT COUNT(*) AS c FROM question_pool").fetchone()["c"]
        if pool_count == 0:
            for block_id in (2, 3, 4):
                for i in range(1, 61):
                    options = [
                        f"Opzione A domanda {i}",
                        f"Opzione B domanda {i}",
                        f"Opzione C domanda {i}",
                        f"Opzione D domanda {i}",
                    ]
                    conn.execute(
                        """
                        INSERT INTO question_pool (block_id, question_text, options_json, correct_option)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            block_id,
                            f"Blocco {block_id} - domanda di esempio {i}",
                            json.dumps(options, ensure_ascii=False),
                            i % 4,
                        ),
                    )

        sessions_count = conn.execute("SELECT COUNT(*) AS c FROM exam_sessions").fetchone()["c"]
        if sessions_count == 0:
            cur = conn.execute(
                """
                INSERT INTO exam_sessions (title, duration_minutes, is_active)
                VALUES (?, ?, 1)
                """,
                ("Sessione Demo Esami", 30),
            )
            session_id = cur.lastrowid
            for i in range(1, 31):
                options = [
                    f"Risposta A {i}",
                    f"Risposta B {i}",
                    f"Risposta C {i}",
                    f"Risposta D {i}",
                ]
                conn.execute(
                    """
                    INSERT INTO exam_questions (session_id, position, question_text, options_json, correct_option, points)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        i,
                        f"Domanda esame {i}",
                        json.dumps(options, ensure_ascii=False),
                        (i + 1) % 4,
                        1,
                    ),
                )


def get_user_by_username(username: str) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_user(user_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_participants() -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE is_trainer = 0 ORDER BY full_name ASC"
        ).fetchall()


def create_participant(
    username: str,
    full_name: str,
    password_hash: str,
    password_plain: str,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO users (
                username,
                full_name,
                password_hash,
                password_plain,
                exam_password_hash,
                exam_password_plain,
                is_trainer
            )
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (
                username,
                full_name,
                password_hash,
                password_plain,
                generate_password_hash("session-required"),
                None,
            ),
        )


def update_participant_access_password(user_id: int, password_plain: str):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, password_plain = ?
            WHERE id = ? AND is_trainer = 0
            """,
            (generate_password_hash(password_plain), password_plain, user_id),
        )


def delete_participant(user_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ? AND is_trainer = 0", (user_id,))


def list_pool_questions(block_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if block_id is None:
            rows = conn.execute("SELECT * FROM question_pool ORDER BY id ASC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM question_pool WHERE block_id = ? ORDER BY id ASC",
                (block_id,),
            ).fetchall()
    for row in rows:
        row["options"] = json.loads(row["options_json"])
    return rows


def create_pool_question(block_id: int, question_text: str, options: list[str], correct_option: int):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO question_pool (block_id, question_text, options_json, correct_option)
            VALUES (?, ?, ?, ?)
            """,
            (block_id, question_text, json.dumps(options, ensure_ascii=False), correct_option),
        )


def get_pool_question(question_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM question_pool WHERE id = ?",
            (question_id,),
        ).fetchone()
    if row:
        row["options"] = json.loads(row["options_json"])
    return row


def update_pool_question(
    question_id: int,
    block_id: int,
    question_text: str,
    options: list[str],
    correct_option: int,
):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE question_pool
            SET block_id = ?, question_text = ?, options_json = ?, correct_option = ?
            WHERE id = ?
            """,
            (
                block_id,
                question_text,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                question_id,
            ),
        )


def count_pool_questions(block_id: int) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM question_pool WHERE block_id = ?",
            (block_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def get_pool_questions_for_block(block_id: int, amount: int = 50) -> list[dict]:
    rows = list_pool_questions(block_id)
    if len(rows) <= amount:
        selected = rows
    else:
        selected = random.sample(rows, amount)
    for row in selected:
        row["options"] = json.loads(row["options_json"])
    return selected


def get_active_exam_session() -> dict | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM exam_sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()


def list_exam_sessions() -> list[dict]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM exam_sessions ORDER BY id DESC").fetchall()


def create_exam_session(title: str, duration_minutes: int, activate: bool = True) -> int:
    with get_db() as conn:
        if activate:
            conn.execute("UPDATE exam_sessions SET is_active = 0")
        cur = conn.execute(
            """
            INSERT INTO exam_sessions (title, duration_minutes, is_active)
            VALUES (?, ?, ?)
            """,
            (title, duration_minutes, 1 if activate else 0),
        )
        return cur.lastrowid


def set_active_exam_session(session_id: int):
    with get_db() as conn:
        conn.execute("UPDATE exam_sessions SET is_active = 0")
        conn.execute("UPDATE exam_sessions SET is_active = 1 WHERE id = ?", (session_id,))


def list_exam_session_participants_map(session_id: int) -> dict[int, bool]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT user_id, is_allowed
            FROM exam_session_participants
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
    return {row["user_id"]: bool(row["is_allowed"]) for row in rows}


def save_exam_session_participants(session_id: int, allowed_user_ids: list[int]):
    allowed = set(allowed_user_ids)
    participants = list_participants()
    with get_db() as conn:
        for p in participants:
            existing = conn.execute(
                """
                SELECT exam_password_hash, exam_password_plain
                FROM exam_session_participants
                WHERE session_id = ? AND user_id = ?
                """,
                (session_id, p["id"]),
            ).fetchone()
            pwd_plain = existing["exam_password_plain"] if existing else None
            pwd_hash = existing["exam_password_hash"] if existing else None
            if p["id"] in allowed and (not pwd_plain or not pwd_hash):
                pwd_plain = generate_exam_password(p["username"])
                pwd_hash = generate_password_hash(pwd_plain)
            conn.execute(
                """
                INSERT INTO exam_session_participants (
                    session_id,
                    user_id,
                    is_allowed,
                    exam_password_hash,
                    exam_password_plain
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, user_id) DO UPDATE SET
                    is_allowed = excluded.is_allowed,
                    exam_password_hash = excluded.exam_password_hash,
                    exam_password_plain = excluded.exam_password_plain
                """,
                (
                    session_id,
                    p["id"],
                    1 if p["id"] in allowed else 0,
                    pwd_hash,
                    pwd_plain,
                ),
            )


def user_can_access_session(user_id: int, session_id: int) -> bool:
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM exam_session_participants WHERE session_id = ?",
            (session_id,),
        ).fetchone()["c"]
        if total == 0:
            return True
        row = conn.execute(
            """
            SELECT is_allowed
            FROM exam_session_participants
            WHERE session_id = ? AND user_id = ?
            LIMIT 1
            """,
            (session_id, user_id),
        ).fetchone()
    if not row:
        return False
    return bool(row["is_allowed"])


def get_session_participant_access(session_id: int, user_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM exam_session_participants
            WHERE session_id = ? AND user_id = ?
            LIMIT 1
            """,
            (session_id, user_id),
        ).fetchone()


def list_session_participant_credentials(session_id: int) -> dict[int, dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT user_id, is_allowed, exam_password_plain
            FROM exam_session_participants
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
    return {
        row["user_id"]: {
            "is_allowed": bool(row["is_allowed"]),
            "exam_password_plain": row["exam_password_plain"],
        }
        for row in rows
    }


def set_session_exam_password(session_id: int, user_id: int, password_plain: str):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exam_session_participants (
                session_id,
                user_id,
                is_allowed,
                exam_password_hash,
                exam_password_plain
            )
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(session_id, user_id) DO UPDATE SET
                is_allowed = 1,
                exam_password_hash = excluded.exam_password_hash,
                exam_password_plain = excluded.exam_password_plain
            """,
            (session_id, user_id, generate_password_hash(password_plain), password_plain),
        )


def list_exam_questions(session_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM exam_questions
            WHERE session_id = ?
            ORDER BY position ASC, id ASC
            """,
            (session_id,),
        ).fetchall()
    for row in rows:
        row["options"] = json.loads(row["options_json"])
    return rows


def create_exam_question(
    session_id: int,
    position: int,
    question_text: str,
    options: list[str],
    correct_option: int,
    points: int,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exam_questions (session_id, position, question_text, options_json, correct_option, points)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                position,
                question_text,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                points,
            ),
        )


def count_exam_questions(session_id: int) -> int:
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM exam_questions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["c"]) if row else 0


def exam_question_position_exists(
    session_id: int, position: int, exclude_question_id: int | None = None
) -> bool:
    with get_db() as conn:
        if exclude_question_id is None:
            row = conn.execute(
                "SELECT 1 AS found FROM exam_questions WHERE session_id = ? AND position = ? LIMIT 1",
                (session_id, position),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT 1 AS found
                FROM exam_questions
                WHERE session_id = ? AND position = ? AND id <> ?
                LIMIT 1
                """,
                (session_id, position, exclude_question_id),
            ).fetchone()
    return bool(row)


def get_exam_question(exam_question_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM exam_questions WHERE id = ?", (exam_question_id,)
        ).fetchone()
    if row:
        row["options"] = json.loads(row["options_json"])
    return row


def update_exam_question(
    exam_question_id: int,
    position: int,
    question_text: str,
    options: list[str],
    correct_option: int,
    points: int,
):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE exam_questions
            SET position = ?, question_text = ?, options_json = ?, correct_option = ?, points = ?
            WHERE id = ?
            """,
            (
                position,
                question_text,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                points,
                exam_question_id,
            ),
        )


def delete_exam_question(exam_question_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM exam_questions WHERE id = ?", (exam_question_id,))


def get_or_create_attempt(user_id: int, session_id: int) -> dict:
    with get_db() as conn:
        attempt = conn.execute(
            """
            SELECT * FROM exam_attempts
            WHERE user_id = ? AND session_id = ? AND status = 'in_progress'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, session_id),
        ).fetchone()
        if attempt:
            return attempt

        started_at = datetime.utcnow().isoformat()
        cur = conn.execute(
            """
            INSERT INTO exam_attempts (user_id, session_id, started_at, status)
            VALUES (?, ?, ?, 'in_progress')
            """,
            (user_id, session_id, started_at),
        )
        attempt_id = cur.lastrowid
        return conn.execute("SELECT * FROM exam_attempts WHERE id = ?", (attempt_id,)).fetchone()


def get_attempt(attempt_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM exam_attempts WHERE id = ?", (attempt_id,)).fetchone()


def save_exam_answer(attempt_id: int, exam_question_id: int, selected_option: int | None, is_standby: bool):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exam_answers (attempt_id, exam_question_id, selected_option, is_standby)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(attempt_id, exam_question_id) DO UPDATE SET
                selected_option = excluded.selected_option,
                is_standby = excluded.is_standby
            """,
            (attempt_id, exam_question_id, selected_option, 1 if is_standby else 0),
        )


def get_attempt_answers_map(attempt_id: int) -> dict[int, dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM exam_answers WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchall()
    return {row["exam_question_id"]: row for row in rows}


def finish_attempt(attempt_id: int):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE exam_attempts
            SET status = 'completed', finished_at = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(), attempt_id),
        )


def build_attempt_report(attempt_id: int) -> dict | None:
    attempt = get_attempt(attempt_id)
    if not attempt:
        return None

    user = get_user(attempt["user_id"])
    with get_db() as conn:
        session = conn.execute(
            "SELECT * FROM exam_sessions WHERE id = ?", (attempt["session_id"],)
        ).fetchone()
    questions = list_exam_questions(attempt["session_id"])
    answers_map = get_attempt_answers_map(attempt_id)

    total_points = sum(q["points"] for q in questions)
    scored_points = 0
    rows = []
    for q in questions:
        ans = answers_map.get(q["id"])
        selected_option = ans["selected_option"] if ans else None
        is_correct = selected_option == q["correct_option"]
        if is_correct:
            scored_points += q["points"]
        rows.append(
            {
                "question": q,
                "selected_option": selected_option,
                "is_correct": is_correct,
                "is_standby": bool(ans["is_standby"]) if ans else False,
            }
        )

    percent = round((scored_points / total_points) * 100, 2) if total_points else 0
    passed = percent >= 60

    return {
        "attempt": attempt,
        "user": user,
        "session": session,
        "rows": rows,
        "scored_points": scored_points,
        "total_points": total_points,
        "percent": percent,
        "passed": passed,
    }


def list_completed_attempts() -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT a.*, u.username, u.full_name, s.title AS session_title
            FROM exam_attempts a
            JOIN users u ON u.id = a.user_id
            JOIN exam_sessions s ON s.id = a.session_id
            WHERE a.status = 'completed'
            ORDER BY a.id DESC
            """
        ).fetchall()
