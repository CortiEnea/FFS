from __future__ import annotations

import json
import os
import random
import sqlite3
import string
from contextlib import contextmanager
from datetime import datetime

from werkzeug.security import generate_password_hash

DB_PATH = os.getenv("DATABASE_PATH") or (
    "/tmp/database.db" if os.getenv("VERCEL") else os.path.join(os.path.dirname(__file__), "database.db")
)


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
                is_trainer INTEGER NOT NULL DEFAULT 0,
                is_admin INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS question_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_id INTEGER NOT NULL CHECK(block_id IN (2,3,4)),
                question_text TEXT NOT NULL,
                image_url TEXT,
                options_json TEXT NOT NULL,
                correct_option INTEGER NOT NULL,
                question_kind TEXT NOT NULL DEFAULT 'single',
                correct_options_json TEXT,
                correct_number TEXT,
                question_number INTEGER NOT NULL
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
                image_url TEXT,
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

            CREATE TABLE IF NOT EXISTS pool_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                block_id INTEGER NOT NULL CHECK(block_id IN (2,3,4)),
                total_questions INTEGER NOT NULL,
                correct_count INTEGER NOT NULL,
                answered_count INTEGER NOT NULL,
                percent REAL NOT NULL,
                completed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        columns = conn.execute("PRAGMA table_info(users)").fetchall()
        names = {col["name"] for col in columns}
        if "exam_password_plain" not in names:
            conn.execute("ALTER TABLE users ADD COLUMN exam_password_plain TEXT")
        if "password_plain" not in names:
            conn.execute("ALTER TABLE users ADD COLUMN password_plain TEXT")
        if "is_admin" not in names:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        pool_columns = conn.execute("PRAGMA table_info(question_pool)").fetchall()
        pool_names = {col["name"] for col in pool_columns}
        if "image_url" not in pool_names:
            conn.execute("ALTER TABLE question_pool ADD COLUMN image_url TEXT")
        if "question_number" not in pool_names:
            conn.execute("ALTER TABLE question_pool ADD COLUMN question_number INTEGER")
            conn.execute(
                "UPDATE question_pool SET question_number = id WHERE question_number IS NULL"
            )
        if "question_kind" not in pool_names:
            conn.execute(
                "ALTER TABLE question_pool ADD COLUMN question_kind TEXT NOT NULL DEFAULT 'single'"
            )
        if "correct_options_json" not in pool_names:
            conn.execute("ALTER TABLE question_pool ADD COLUMN correct_options_json TEXT")
        if "correct_number" not in pool_names:
            conn.execute("ALTER TABLE question_pool ADD COLUMN correct_number TEXT")
        # Backfill: existing questions were single-choice.
        conn.execute(
            """
            UPDATE question_pool
            SET
              question_kind = COALESCE(NULLIF(question_kind, ''), 'single'),
              correct_options_json = CASE
                WHEN correct_options_json IS NULL OR correct_options_json = ''
                THEN ('[' || COALESCE(correct_option, 0) || ']')
                ELSE correct_options_json
              END
            WHERE question_kind IS NULL OR question_kind = '' OR correct_options_json IS NULL OR correct_options_json = ''
            """
        )
        try:
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_question_pool_question_number
                ON question_pool(question_number)
                """
            )
        except sqlite3.OperationalError:
            pass
        exam_q_columns = conn.execute("PRAGMA table_info(exam_questions)").fetchall()
        exam_q_names = {col["name"] for col in exam_q_columns}
        if "image_url" not in exam_q_names:
            conn.execute("ALTER TABLE exam_questions ADD COLUMN image_url TEXT")
        if "question_kind" not in exam_q_names:
            conn.execute("ALTER TABLE exam_questions ADD COLUMN question_kind TEXT NOT NULL DEFAULT 'single'")
        if "correct_options_json" not in exam_q_names:
            conn.execute("ALTER TABLE exam_questions ADD COLUMN correct_options_json TEXT")
        if "correct_number" not in exam_q_names:
            conn.execute("ALTER TABLE exam_questions ADD COLUMN correct_number TEXT")
        ea_columns = conn.execute("PRAGMA table_info(exam_answers)").fetchall()
        ea_names = {col["name"] for col in ea_columns}
        if "selected_options_json" not in ea_names:
            conn.execute("ALTER TABLE exam_answers ADD COLUMN selected_options_json TEXT")
        if "selected_number" not in ea_names:
            conn.execute("ALTER TABLE exam_answers ADD COLUMN selected_number TEXT")
        sp_columns = conn.execute("PRAGMA table_info(exam_session_participants)").fetchall()
        sp_names = {col["name"] for col in sp_columns}
        if "exam_password_hash" not in sp_names:
            conn.execute("ALTER TABLE exam_session_participants ADD COLUMN exam_password_hash TEXT")
        if "exam_password_plain" not in sp_names:
            conn.execute("ALTER TABLE exam_session_participants ADD COLUMN exam_password_plain TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for migration_name in (
            "pool_clear_reset_sequence_v1",
            "pool_clear_reset_sequence_v2",
        ):
            if not conn.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?",
                (migration_name,),
            ).fetchone():
                conn.execute("DELETE FROM question_pool")
                conn.execute("DELETE FROM sqlite_sequence WHERE name = 'question_pool'")
                conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)",
                    (migration_name,),
                )

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
    """
    Demo seeding.

    Default behavior:
    - seed only when DB is empty (first boot), preserving users/reports/passwords on restart.

    Optional reset behavior:
    - set DEMO_RESET_ON_START=1 to force full reset + reseed on every start.
    """
    seed_image_url = "/static/ffs-logo.svg"
    force_reset = (os.getenv("DEMO_RESET_ON_START") or "0").strip() == "1"

    with get_db() as conn:
        users_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        should_reset = force_reset or int(users_count or 0) == 0
        if not should_reset:
            # Keep current state (reports/passwords/users) across restarts.
            conn.execute("UPDATE users SET is_trainer = 1 WHERE is_admin = 1")
            return

        # Clear runtime/demo data. Keep schema_migrations intact.
        conn.executescript(
            """
            DELETE FROM exam_answers;
            DELETE FROM exam_attempts;
            DELETE FROM exam_session_participants;
            DELETE FROM exam_questions;
            DELETE FROM exam_sessions;
            DELETE FROM pool_attempts;
            DELETE FROM question_pool;
            DELETE FROM users;

            DELETE FROM sqlite_sequence WHERE name IN (
              'exam_answers',
              'exam_attempts',
              'exam_session_participants',
              'exam_questions',
              'exam_sessions',
              'pool_attempts',
              'question_pool',
              'users'
            );
            """
        )

        # Users
        conn.execute(
            """
            INSERT INTO users (
              username, full_name, password_hash, password_plain,
              exam_password_hash, exam_password_plain,
              is_trainer, is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, 1)
            """,
            (
                "admin",
                "Admin",
                generate_password_hash("admin123"),
                "admin123",
                generate_password_hash("session-required"),
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO users (
              username, full_name, password_hash, password_plain,
              exam_password_hash, exam_password_plain,
              is_trainer, is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, 0)
            """,
            (
                "trainer",
                "Formatore Demo",
                generate_password_hash("trainer123"),
                "trainer123",
                generate_password_hash("session-required"),
                None,
            ),
        )
        conn.execute(
            """
            INSERT INTO users (
              username, full_name, password_hash, password_plain,
              exam_password_hash, exam_password_plain,
              is_trainer, is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                "mario.rossi",
                "Mario Rossi",
                generate_password_hash("password123"),
                "password123",
                generate_password_hash("esame123"),
                "esame123",
            ),
        )
        conn.execute(
            """
            INSERT INTO users (
              username, full_name, password_hash, password_plain,
              exam_password_hash, exam_password_plain,
              is_trainer, is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
            """,
            (
                "ene",
                "Enny",
                generate_password_hash("password123"),
                "password123",
                generate_password_hash("esame123"),
                "esame123",
            ),
        )

        # Admin accede come formatore: ogni utente admin deve essere anche trainer.
        conn.execute("UPDATE users SET is_trainer = 1 WHERE is_admin = 1")

        # Pool questions (150), with image.
        regenerate_demo_pool_questions(
            total=150,
            number_count=20,
            single_count=30,
            multi_one_count=40,
            multi_many_count=60,
            image_url=seed_image_url,
            conn=conn,
        )

        # Exam session + questions (30), with image. Attempts remain empty.
        cur = conn.execute(
            """
            INSERT INTO exam_sessions (title, duration_minutes, is_active)
            VALUES (?, ?, 1)
            """,
            ("Test primo esame", 30),
        )
        session_id = cur.lastrowid
        for i in range(1, 31):
            options = [
                f"Risposta A {i}",
                f"Risposta B {i}",
                f"Risposta C {i}",
                f"Risposta D {i}",
            ]
            correct = (i + 1) % 4
            conn.execute(
                """
                INSERT INTO exam_questions (
                  session_id, position, question_text, image_url,
                  options_json, correct_option, points,
                  question_kind, correct_options_json, correct_number
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'single', ?, NULL)
                """,
                (
                    session_id,
                    i,
                    f"{i}: Domanda demo esame",
                    seed_image_url,
                    json.dumps(options, ensure_ascii=False),
                    correct,
                    1,
                    json.dumps([correct], ensure_ascii=False),
                ),
            )


def regenerate_demo_pool_questions(
    *,
    total: int = 150,
    number_count: int = 20,
    single_count: int = 30,
    multi_one_count: int = 40,
    multi_many_count: int = 60,
    image_url: str | None = None,
    conn: sqlite3.Connection | None = None,
):
    if total <= 0:
        raise ValueError("total must be > 0")
    if number_count < 0 or single_count < 0 or multi_one_count < 0 or multi_many_count < 0:
        raise ValueError("counts must be >= 0")
    if number_count + single_count + multi_one_count + multi_many_count != total:
        raise ValueError("counts must sum to total")

    plan: list[str] = (
        (["number"] * number_count)
        + (["single"] * single_count)
        + (["multi_one"] * multi_one_count)
        + (["multi_many"] * multi_many_count)
    )
    random.shuffle(plan)

    if conn is None:
        with get_db() as _conn:
            regenerate_demo_pool_questions(
                total=total,
                number_count=number_count,
                single_count=single_count,
                multi_one_count=multi_one_count,
                multi_many_count=multi_many_count,
                image_url=image_url,
                conn=_conn,
            )
        return

    conn.execute("DELETE FROM question_pool")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'question_pool'")

    for i, kind in enumerate(plan, start=1):
        block_id = 2 + ((i - 1) % 3)
        if kind == "number":
            options: list[str] = []
            correct_options: list[int] = []
            correct_number = str((i % 97) + 1)
        else:
            options = [
                f"Opzione A (q{i})",
                f"Opzione B (q{i})",
                f"Opzione C (q{i})",
                f"Opzione D (q{i})",
            ]
            correct_number = None
            if kind in ("single", "multi_one"):
                correct_options = [i % 4]
            else:
                a = i % 4
                b = (i + 2) % 4
                c = (i + 3) % 4 if i % 5 == 0 else None
                correct_options = sorted({x for x in (a, b, c) if x is not None})

        conn.execute(
            """
            INSERT INTO question_pool (
                block_id,
                question_text,
                image_url,
                options_json,
                correct_option,
                question_kind,
                correct_options_json,
                correct_number,
                question_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block_id,
                f"{i}: Domanda demo ({kind})",
                image_url,
                json.dumps(options, ensure_ascii=False),
                int(correct_options[0]) if correct_options else 0,
                kind,
                json.dumps(correct_options, ensure_ascii=False),
                correct_number,
                i,
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
            "SELECT * FROM users WHERE is_trainer = 0 AND is_admin = 0 ORDER BY full_name ASC"
        ).fetchall()


def list_trainers() -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE is_trainer = 1 AND is_admin = 0 ORDER BY full_name ASC"
        ).fetchall()


def list_admins() -> list[dict]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE is_admin = 1 ORDER BY full_name ASC"
        ).fetchall()


def create_trainer(
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
                is_trainer,
                is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, 0)
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
                is_trainer,
                is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, 0)
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


def update_user_access_password(user_id: int, password_plain: str):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, password_plain = ?
            WHERE id = ? AND is_admin = 0
            """,
            (generate_password_hash(password_plain), password_plain, user_id),
        )


def delete_user(user_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM users WHERE id = ? AND is_admin = 0",
            (user_id,),
        )
        return cur.rowcount > 0


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


def next_available_question_number() -> int:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT question_number FROM question_pool WHERE question_number IS NOT NULL"
        ).fetchall()
    used = {int(r["question_number"]) for r in rows}
    n = 1
    while n in used:
        n += 1
    return n


def list_pool_questions(block_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if block_id is None:
            rows = conn.execute(
                "SELECT * FROM question_pool ORDER BY question_number ASC, id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM question_pool WHERE block_id = ? ORDER BY question_number ASC, id ASC",
                (block_id,),
            ).fetchall()
    for row in rows:
        row["options"] = json.loads(row["options_json"])
        kind = row.get("question_kind") or "single"
        row["question_kind"] = kind
        if row.get("correct_options_json"):
            try:
                row["correct_options"] = json.loads(row["correct_options_json"])
            except Exception:
                row["correct_options"] = [int(row.get("correct_option") or 0)]
        else:
            row["correct_options"] = [int(row.get("correct_option") or 0)]
    return rows


def create_pool_question(
    block_id: int,
    question_text: str,
    image_url: str | None,
    options: list[str],
    correct_option: int,
):
    qnum = next_available_question_number()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO question_pool (
                block_id,
                question_text,
                image_url,
                options_json,
                correct_option,
                question_kind,
                correct_options_json,
                correct_number,
                question_number
            )
            VALUES (?, ?, ?, ?, ?, 'single', ?, NULL, ?)
            """,
            (
                block_id,
                question_text,
                image_url,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                json.dumps([correct_option], ensure_ascii=False),
                qnum,
            ),
        )


def delete_pool_question(question_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM question_pool WHERE id = ?", (question_id,))
        return cur.rowcount > 0


def get_pool_question(question_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM question_pool WHERE id = ?",
            (question_id,),
        ).fetchone()
    if row:
        row["options"] = json.loads(row["options_json"])
        row["question_kind"] = row.get("question_kind") or "single"
        if row.get("correct_options_json"):
            try:
                row["correct_options"] = json.loads(row["correct_options_json"])
            except Exception:
                row["correct_options"] = [int(row.get("correct_option") or 0)]
        else:
            row["correct_options"] = [int(row.get("correct_option") or 0)]
    return row


def update_pool_question(
    question_id: int,
    block_id: int,
    question_text: str,
    image_url: str | None,
    options: list[str],
    correct_option: int,
):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE question_pool
            SET block_id = ?, question_text = ?, image_url = ?, options_json = ?, correct_option = ?,
                question_kind = 'single',
                correct_options_json = ?,
                correct_number = NULL
            WHERE id = ?
            """,
            (
                block_id,
                question_text,
                image_url,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                json.dumps([correct_option], ensure_ascii=False),
                question_id,
            ),
        )


def create_pool_question_typed(
    block_id: int,
    question_text: str,
    image_url: str | None,
    question_kind: str,
    options: list[str] | None,
    correct_options: list[int] | None,
    correct_number: str | None,
):
    qnum = next_available_question_number()
    kind = (question_kind or "single").strip().lower()
    if kind not in ("number", "single", "multi_one", "multi_many"):
        kind = "single"
    opts = options or []
    corr_opts = correct_options or []
    corr_num = correct_number

    if kind == "number":
        opts = []
        corr_opts = []
        # keep correct_option required by schema
        correct_option = 0
    else:
        if len(opts) != 4:
            raise ValueError("options")
        if any(not o for o in opts):
            raise ValueError("options")
        if kind == "single":
            if len(corr_opts) != 1:
                raise ValueError("correct")
        elif kind == "multi_one":
            if len(corr_opts) != 1:
                raise ValueError("correct")
        elif kind == "multi_many":
            if len(corr_opts) < 1:
                raise ValueError("correct")
        if any(int(i) not in (0, 1, 2, 3) for i in corr_opts):
            raise ValueError("correct")
        correct_option = int(corr_opts[0])

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO question_pool (
                block_id,
                question_text,
                image_url,
                options_json,
                correct_option,
                question_kind,
                correct_options_json,
                correct_number,
                question_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block_id,
                question_text,
                image_url,
                json.dumps(opts, ensure_ascii=False),
                int(correct_option),
                kind,
                json.dumps(corr_opts, ensure_ascii=False),
                corr_num,
                qnum,
            ),
        )


def update_pool_question_typed(
    question_id: int,
    block_id: int,
    question_text: str,
    image_url: str | None,
    question_kind: str,
    options: list[str] | None,
    correct_options: list[int] | None,
    correct_number: str | None,
):
    kind = (question_kind or "single").strip().lower()
    if kind not in ("number", "single", "multi_one", "multi_many"):
        kind = "single"
    opts = options or []
    corr_opts = correct_options or []
    corr_num = correct_number

    if kind == "number":
        opts = []
        corr_opts = []
        correct_option = 0
    else:
        if len(opts) != 4:
            raise ValueError("options")
        if any(not o for o in opts):
            raise ValueError("options")
        if kind in ("single", "multi_one") and len(corr_opts) != 1:
            raise ValueError("correct")
        if kind == "multi_many" and len(corr_opts) < 1:
            raise ValueError("correct")
        if any(int(i) not in (0, 1, 2, 3) for i in corr_opts):
            raise ValueError("correct")
        correct_option = int(corr_opts[0])

    with get_db() as conn:
        conn.execute(
            """
            UPDATE question_pool
            SET block_id = ?,
                question_text = ?,
                image_url = ?,
                options_json = ?,
                correct_option = ?,
                question_kind = ?,
                correct_options_json = ?,
                correct_number = ?
            WHERE id = ?
            """,
            (
                block_id,
                question_text,
                image_url,
                json.dumps(opts, ensure_ascii=False),
                int(correct_option),
                kind,
                json.dumps(corr_opts, ensure_ascii=False),
                corr_num,
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


def get_auto_pool_block_id() -> int:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT block_id, COUNT(*) AS c
            FROM question_pool
            WHERE block_id IN (2, 3, 4)
            GROUP BY block_id
            ORDER BY c ASC, block_id ASC
            LIMIT 1
            """
        ).fetchone()
    if row:
        return int(row["block_id"])
    return 2


def get_pool_questions_for_block(block_id: int, amount: int = 50) -> list[dict]:
    rows = list_pool_questions(block_id)
    if len(rows) <= amount:
        selected = random.sample(rows, len(rows))
    else:
        selected = random.sample(rows, amount)
    for row in selected:
        row["options"] = json.loads(row["options_json"])
    return selected


def count_pool_questions_total() -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM question_pool").fetchone()
    return int(row["c"]) if row else 0


def get_pool_questions_random(amount: int = 50) -> list[dict]:
    rows = list_pool_questions(None)
    if len(rows) <= amount:
        selected = random.sample(rows, len(rows))
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


def update_exam_session(session_id: int, title: str, duration_minutes: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE exam_sessions SET title = ?, duration_minutes = ? WHERE id = ?",
            (title, duration_minutes, session_id),
        )


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
        kind = row.get("question_kind") or "single"
        row["question_kind"] = kind
        if row.get("correct_options_json"):
            try:
                row["correct_options"] = json.loads(row["correct_options_json"])
            except Exception:
                row["correct_options"] = [int(row.get("correct_option") or 0)]
        else:
            row["correct_options"] = [int(row.get("correct_option") or 0)]
    return rows


def create_exam_question(
    session_id: int,
    position: int,
    question_text: str,
    image_url: str | None,
    options: list[str],
    correct_option: int,
    points: int,
    question_kind: str = "single",
    correct_options: list[int] | None = None,
    correct_number: str | None = None,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exam_questions (
                session_id,
                position,
                question_text,
                image_url,
                options_json,
                correct_option,
                points,
                question_kind,
                correct_options_json,
                correct_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                position,
                question_text,
                image_url,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                points,
                question_kind,
                json.dumps(correct_options, ensure_ascii=False) if correct_options else None,
                correct_number,
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
        kind = row.get("question_kind") or "single"
        row["question_kind"] = kind
        if row.get("correct_options_json"):
            try:
                row["correct_options"] = json.loads(row["correct_options_json"])
            except Exception:
                row["correct_options"] = [int(row.get("correct_option") or 0)]
        else:
            row["correct_options"] = [int(row.get("correct_option") or 0)]
    return row


def update_exam_question(
    exam_question_id: int,
    position: int,
    question_text: str,
    image_url: str | None,
    options: list[str],
    correct_option: int,
    points: int,
    question_kind: str = "single",
    correct_options: list[int] | None = None,
    correct_number: str | None = None,
):
    with get_db() as conn:
        conn.execute(
            """
            UPDATE exam_questions
            SET position = ?, question_text = ?, image_url = ?, options_json = ?, correct_option = ?,
                points = ?, question_kind = ?, correct_options_json = ?, correct_number = ?
            WHERE id = ?
            """,
            (
                position,
                question_text,
                image_url,
                json.dumps(options, ensure_ascii=False),
                correct_option,
                points,
                question_kind,
                json.dumps(correct_options, ensure_ascii=False) if correct_options else None,
                correct_number,
                exam_question_id,
            ),
        )


def swap_exam_question_positions(question_id_a: int, question_id_b: int):
    with get_db() as conn:
        a = conn.execute("SELECT id, position FROM exam_questions WHERE id = ?", (question_id_a,)).fetchone()
        b = conn.execute("SELECT id, position FROM exam_questions WHERE id = ?", (question_id_b,)).fetchone()
        if not a or not b:
            return
        conn.execute("UPDATE exam_questions SET position = ? WHERE id = ?", (b["position"], a["id"]))
        conn.execute("UPDATE exam_questions SET position = ? WHERE id = ?", (a["position"], b["id"]))


def delete_exam_question(exam_question_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM exam_questions WHERE id = ?", (exam_question_id,))


def reorder_exam_questions(session_id: int):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM exam_questions WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
        for i, row in enumerate(rows):
            conn.execute(
                "UPDATE exam_questions SET position = ? WHERE id = ?",
                (i + 1, row["id"]),
            )


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


def get_in_progress_attempt(user_id: int, session_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute(
            """
            SELECT * FROM exam_attempts
            WHERE user_id = ? AND session_id = ? AND status = 'in_progress'
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, session_id),
        ).fetchone()


def has_completed_attempt(user_id: int, session_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT 1 AS found
            FROM exam_attempts
            WHERE user_id = ? AND session_id = ? AND status = 'completed'
            LIMIT 1
            """,
            (user_id, session_id),
        ).fetchone()
    return bool(row)


def get_attempt(attempt_id: int) -> dict | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM exam_attempts WHERE id = ?", (attempt_id,)).fetchone()


def save_exam_answer(
    attempt_id: int,
    exam_question_id: int,
    selected_option: int | None,
    is_standby: bool,
    selected_options: list[int] | None = None,
    selected_number: str | None = None,
):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO exam_answers (attempt_id, exam_question_id, selected_option, is_standby, selected_options_json, selected_number)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(attempt_id, exam_question_id) DO UPDATE SET
                selected_option = excluded.selected_option,
                is_standby = excluded.is_standby,
                selected_options_json = excluded.selected_options_json,
                selected_number = excluded.selected_number
            """,
            (
                attempt_id,
                exam_question_id,
                selected_option,
                1 if is_standby else 0,
                json.dumps(selected_options, ensure_ascii=False) if selected_options is not None else None,
                selected_number,
            ),
        )


def get_attempt_answers_map(attempt_id: int) -> dict[int, dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM exam_answers WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchall()
    for row in rows:
        if row.get("selected_options_json"):
            try:
                row["selected_options"] = json.loads(row["selected_options_json"])
            except Exception:
                row["selected_options"] = None
        else:
            row["selected_options"] = None
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


def delete_attempt(attempt_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM exam_attempts WHERE id = ?", (attempt_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM exam_attempts WHERE id = ?", (attempt_id,))
        return True


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
        kind = q.get("question_kind") or "single"
        if kind == "number":
            given = (ans.get("selected_number") or "").strip() if ans else ""
            correct_num = (q.get("correct_number") or "").strip()
            is_correct = given == correct_num and given != ""
        elif kind == "multi_many":
            given = sorted(ans.get("selected_options") or []) if ans else []
            correct_opts = sorted(q.get("correct_options") or [])
            is_correct = given == correct_opts and len(given) > 0
        else:
            selected_option = ans["selected_option"] if ans else None
            is_correct = selected_option == q["correct_option"]
        if is_correct:
            scored_points += q["points"]
        rows.append(
            {
                "question": q,
                "answer": ans,
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


# ── Pool attempts ──────────────────────────────────────────────────

def save_pool_attempt(user_id: int, block_id: int, total_questions: int,
                      correct_count: int, answered_count: int) -> int:
    percent = round((correct_count / total_questions) * 100, 2) if total_questions else 0
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO pool_attempts (user_id, block_id, total_questions,
                                       correct_count, answered_count, percent)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, block_id, total_questions, correct_count, answered_count, percent),
        )
        return cur.lastrowid


def list_pool_attempts(user_id: int, block_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if block_id is not None:
            return conn.execute(
                """
                SELECT * FROM pool_attempts
                WHERE user_id = ? AND block_id = ?
                ORDER BY completed_at DESC
                """,
                (user_id, block_id),
            ).fetchall()
        return conn.execute(
            """
            SELECT * FROM pool_attempts
            WHERE user_id = ?
            ORDER BY completed_at DESC
            """,
            (user_id,),
        ).fetchall()
