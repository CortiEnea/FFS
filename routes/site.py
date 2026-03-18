from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

import db

site = Blueprint("site", __name__)
PRACTICE_QUESTION_COUNT = 50
EXAM_QUESTION_COUNT = 30


def _participant_required():
    if not session.get("user_id"):
        return False
    return True


@site.get("/")
def index():
    if session.get("trainer_id"):
        return redirect(url_for("trainer.dashboard"))
    if _participant_required():
        return redirect(url_for("site.dashboard"))
    return redirect(url_for("site.login"))


@site.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = (request.form.get("role") or "participant").strip().lower()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = db.get_user_by_username(username)

        if role not in ("participant", "trainer"):
            flash("Ruolo non valido.", "error")
            return redirect(url_for("site.login"))

        if role == "trainer":
            if not user or not user["is_trainer"]:
                flash("Credenziali formatore non valide.", "error")
                return redirect(url_for("site.login"))
            if not check_password_hash(user["password_hash"], password):
                flash("Credenziali formatore non valide.", "error")
                return redirect(url_for("site.login"))

            session.pop("user_id", None)
            session.pop("user_full_name", None)
            session["trainer_id"] = user["id"]
            session["trainer_name"] = user["full_name"]
            flash("Accesso formatore effettuato.", "success")
            return redirect(url_for("trainer.dashboard"))

        if not user or user["is_trainer"]:
            flash("Utente partecipante non valido.", "error")
            return redirect(url_for("site.login"))

        if not check_password_hash(user["password_hash"], password):
            flash("Password errata.", "error")
            return redirect(url_for("site.login"))

        session.pop("trainer_id", None)
        session.pop("trainer_name", None)
        session["user_id"] = user["id"]
        session["user_full_name"] = user["full_name"]
        flash("Accesso effettuato.", "success")
        return redirect(url_for("site.dashboard"))

    return render_template("login.html")


@site.get("/logout")
def logout():
    session.clear()
    flash("Logout effettuato.", "success")
    return redirect(url_for("site.login"))


@site.get("/dashboard")
def dashboard():
    if not _participant_required():
        return redirect(url_for("site.login"))
    return render_template("dashboard.html", full_name=session.get("user_full_name"))


@site.route("/practice/<int:block_id>/start", methods=["GET"])
def practice_start(block_id: int):
    if not _participant_required():
        return redirect(url_for("site.login"))
    if block_id not in (2, 3, 4):
        flash("Blocco non valido.", "error")
        return redirect(url_for("site.dashboard"))

    available = db.count_pool_questions(block_id)
    if available < PRACTICE_QUESTION_COUNT:
        flash(
            f"Per avviare il blocco {block_id} servono almeno {PRACTICE_QUESTION_COUNT} domande nel pool.",
            "error",
        )
        return redirect(url_for("site.dashboard"))
    questions = db.get_pool_questions_for_block(block_id, amount=PRACTICE_QUESTION_COUNT)

    session["practice"] = {
        "block_id": block_id,
        "question_ids": [q["id"] for q in questions],
        "index": 0,
        "correct_count": 0,
        "last_feedback": None,
    }
    return redirect(url_for("site.practice_question", block_id=block_id))


@site.route("/practice/<int:block_id>/question", methods=["GET", "POST"])
def practice_question(block_id: int):
    if not _participant_required():
        return redirect(url_for("site.login"))

    state = session.get("practice")
    if not state or state.get("block_id") != block_id:
        return redirect(url_for("site.practice_start", block_id=block_id))

    questions = db.list_pool_questions(block_id)
    by_id = {q["id"]: q for q in questions}
    qids = state["question_ids"]
    idx = state["index"]

    if idx >= len(qids):
        return redirect(url_for("site.practice_result", block_id=block_id))

    current = by_id.get(qids[idx])
    if not current:
        flash("Domanda non disponibile.", "error")
        return redirect(url_for("site.practice_result", block_id=block_id))

    feedback = state.get("last_feedback")

    if request.method == "POST":
        action = request.form.get("action", "answer")
        if action == "next":
            state["index"] += 1
            state["last_feedback"] = None
            session["practice"] = state
            if state["index"] >= len(qids):
                return redirect(url_for("site.practice_result", block_id=block_id))
            return redirect(url_for("site.practice_question", block_id=block_id))

        selected = request.form.get("selected_option")
        if selected is None:
            flash("Seleziona una risposta.", "error")
            return redirect(url_for("site.practice_question", block_id=block_id))

        try:
            selected_int = int(selected)
        except ValueError:
            flash("Risposta non valida.", "error")
            return redirect(url_for("site.practice_question", block_id=block_id))
        if selected_int not in (0, 1, 2, 3):
            flash("Risposta non valida.", "error")
            return redirect(url_for("site.practice_question", block_id=block_id))
        is_correct = selected_int == current["correct_option"]
        if is_correct:
            state["correct_count"] += 1

        state["last_feedback"] = {
            "selected_option": selected_int,
            "correct_option": current["correct_option"],
            "is_correct": is_correct,
        }
        session["practice"] = state
        feedback = state["last_feedback"]

    return render_template(
        "practice_question.html",
        block_id=block_id,
        question=current,
        index=idx + 1,
        total=len(qids),
        feedback=feedback,
    )


@site.get("/practice/<int:block_id>/result")
def practice_result(block_id: int):
    if not _participant_required():
        return redirect(url_for("site.login"))
    state = session.get("practice")
    if not state or state.get("block_id") != block_id:
        return redirect(url_for("site.dashboard"))

    total = len(state["question_ids"])
    correct = state["correct_count"]
    percent = round((correct / total) * 100, 2) if total else 0
    session.pop("practice", None)
    return render_template(
        "practice_result.html",
        block_id=block_id,
        total=total,
        correct=correct,
        percent=percent,
    )


def _remaining_seconds(attempt: dict, exam_session: dict) -> int:
    started = datetime.fromisoformat(attempt["started_at"])
    elapsed = int((datetime.utcnow() - started).total_seconds())
    duration = int(exam_session["duration_minutes"]) * 60
    return max(duration - elapsed, 0)


@site.route("/exam/start", methods=["GET", "POST"])
def exam_start():
    if not _participant_required():
        return redirect(url_for("site.login"))

    exam_session = db.get_active_exam_session()
    if not exam_session:
        flash("Nessuna sessione esame attiva.", "error")
        return redirect(url_for("site.dashboard"))

    questions = db.list_exam_questions(exam_session["id"])
    if len(questions) != EXAM_QUESTION_COUNT:
        flash(
            f"La sessione esame deve contenere esattamente {EXAM_QUESTION_COUNT} domande.",
            "error",
        )
        return redirect(url_for("site.dashboard"))
    if not db.user_can_access_session(session["user_id"], exam_session["id"]):
        flash("Non sei abilitato a questa sessione esame.", "error")
        return redirect(url_for("site.dashboard"))

    if request.method == "POST":
        exam_password = request.form.get("exam_password") or ""
        session_access = db.get_session_participant_access(exam_session["id"], session["user_id"])
        if not session_access or not session_access["exam_password_hash"]:
            flash(
                "Password esame non ancora configurata per questa sessione. Contatta il formatore.",
                "error",
            )
            return redirect(url_for("site.exam_start"))
        if not check_password_hash(session_access["exam_password_hash"], exam_password):
            flash("Password esame non valida.", "error")
            return redirect(url_for("site.exam_start"))

        attempt = db.get_or_create_attempt(session["user_id"], exam_session["id"])
        session["exam_attempt_id"] = attempt["id"]
        session["exam_position"] = 0
        return redirect(url_for("site.exam_question"))

    return render_template("exam_start.html", exam_session=exam_session, question_count=len(questions))


@site.route("/exam/question", methods=["GET", "POST"])
def exam_question():
    if not _participant_required():
        return redirect(url_for("site.login"))

    attempt_id = session.get("exam_attempt_id")
    if not attempt_id:
        return redirect(url_for("site.exam_start"))

    attempt = db.get_attempt(attempt_id)
    if not attempt or attempt["status"] != "in_progress":
        return redirect(url_for("site.exam_finished", attempt_id=attempt_id))

    exam_session = db.get_active_exam_session()
    if not exam_session or exam_session["id"] != attempt["session_id"]:
        with db.get_db() as conn:
            exam_session = conn.execute(
                "SELECT * FROM exam_sessions WHERE id = ?",
                (attempt["session_id"],),
            ).fetchone()
    questions = db.list_exam_questions(attempt["session_id"])
    answers_map = db.get_attempt_answers_map(attempt_id)
    if not questions:
        flash("Nessuna domanda disponibile.", "error")
        return redirect(url_for("site.dashboard"))

    remaining = _remaining_seconds(attempt, exam_session)
    if remaining == 0:
        db.finish_attempt(attempt_id)
        return redirect(url_for("site.exam_finished", attempt_id=attempt_id))

    pos = int(session.get("exam_position", 0))
    if pos < 0:
        pos = 0
    if pos >= len(questions):
        pos = len(questions) - 1
    current = questions[pos]
    existing = answers_map.get(current["id"])

    if request.method == "POST":
        action = request.form.get("action", "save_next")
        selected_raw = request.form.get("selected_option")
        if selected_raw in (None, ""):
            selected = None
        else:
            try:
                selected = int(selected_raw)
            except ValueError:
                flash("Risposta non valida.", "error")
                return redirect(url_for("site.exam_question"))
            if selected not in (0, 1, 2, 3):
                flash("Risposta non valida.", "error")
                return redirect(url_for("site.exam_question"))
        standby = bool(request.form.get("standby"))
        db.save_exam_answer(attempt_id, current["id"], selected, standby)

        if action == "save_next":
            session["exam_position"] = min(pos + 1, len(questions) - 1)
            return redirect(url_for("site.exam_question"))
        if action == "save_prev":
            session["exam_position"] = max(pos - 1, 0)
            return redirect(url_for("site.exam_question"))
        if action == "review":
            return redirect(url_for("site.exam_review"))

    return render_template(
        "exam_question.html",
        exam_session=exam_session,
        question=current,
        index=pos + 1,
        total=len(questions),
        answer=existing,
        remaining_seconds=remaining,
    )


@site.route("/exam/review", methods=["GET", "POST"])
def exam_review():
    if not _participant_required():
        return redirect(url_for("site.login"))

    attempt_id = session.get("exam_attempt_id")
    if not attempt_id:
        return redirect(url_for("site.exam_start"))

    attempt = db.get_attempt(attempt_id)
    if not attempt:
        return redirect(url_for("site.dashboard"))

    questions = db.list_exam_questions(attempt["session_id"])
    answers_map = db.get_attempt_answers_map(attempt_id)
    exam_session = db.get_active_exam_session()
    if not exam_session or exam_session["id"] != attempt["session_id"]:
        with db.get_db() as conn:
            exam_session = conn.execute(
                "SELECT * FROM exam_sessions WHERE id = ?",
                (attempt["session_id"],),
            ).fetchone()

    if attempt["status"] == "completed":
        return redirect(url_for("site.exam_finished", attempt_id=attempt_id))

    remaining = _remaining_seconds(attempt, exam_session)
    if remaining == 0:
        db.finish_attempt(attempt_id)
        return redirect(url_for("site.exam_finished", attempt_id=attempt_id))

    rows = []
    unanswered = 0
    for i, q in enumerate(questions):
        ans = answers_map.get(q["id"])
        selected = ans["selected_option"] if ans else None
        standby = bool(ans["is_standby"]) if ans else False
        if selected is None:
            unanswered += 1
        rows.append({"i": i, "q": q, "selected": selected, "standby": standby})

    if request.method == "POST":
        if unanswered > 0:
            flash("Puoi terminare solo quando tutte le domande hanno una risposta.", "error")
            return redirect(url_for("site.exam_review"))
        db.finish_attempt(attempt_id)
        return redirect(url_for("site.exam_finished", attempt_id=attempt_id))

    return render_template(
        "exam_review.html",
        rows=rows,
        unanswered=unanswered,
        remaining_seconds=remaining,
    )


@site.get("/exam/goto/<int:position>")
def exam_goto(position: int):
    if not _participant_required():
        return redirect(url_for("site.login"))
    session["exam_position"] = max(position, 0)
    return redirect(url_for("site.exam_question"))


@site.get("/exam/finished/<int:attempt_id>")
def exam_finished(attempt_id: int):
    if not _participant_required():
        return redirect(url_for("site.login"))

    report = db.build_attempt_report(attempt_id)
    if not report:
        flash("Tentativo non trovato.", "error")
        return redirect(url_for("site.dashboard"))
    if report["attempt"]["user_id"] != session["user_id"]:
        flash("Operazione non autorizzata.", "error")
        return redirect(url_for("site.dashboard"))

    session.pop("exam_attempt_id", None)
    session.pop("exam_position", None)
    return render_template("exam_finished.html", report=report)
