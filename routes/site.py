from __future__ import annotations

from datetime import datetime
import random

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

            session.clear()
            session["trainer_id"] = user["id"]
            session["trainer_name"] = user["full_name"]
            session["trainer_is_admin"] = bool(user.get("is_admin"))
            flash("Accesso formatore effettuato.", "success")
            return redirect(url_for("trainer.dashboard"))

        if not user or user["is_trainer"]:
            flash("Utente partecipante non valido.", "error")
            return redirect(url_for("site.login"))

        if not check_password_hash(user["password_hash"], password):
            flash("Password errata.", "error")
            return redirect(url_for("site.login"))

        session.clear()
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
    uid = session["user_id"]
    pool_history = {}
    for bid in (2, 3, 4):
        attempts = db.list_pool_attempts(uid, bid)
        pool_history[bid] = {
            "count": len(attempts),
            "last": attempts[0] if attempts else None,
        }
    return render_template(
        "dashboard.html",
        full_name=session.get("user_full_name"),
        pool_history=pool_history,
    )


@site.route("/practice/<int:block_id>/start", methods=["GET"])
def practice_start(block_id: int):
    if not _participant_required():
        return redirect(url_for("site.login"))
    if block_id not in (2, 3, 4):
        flash("Blocco non valido.", "error")
        return redirect(url_for("site.dashboard"))

    available = db.count_pool_questions_total()
    if available < PRACTICE_QUESTION_COUNT:
        flash(
            f"Per avviare l'esercitazione servono almeno {PRACTICE_QUESTION_COUNT} domande nel pool.",
            "error",
        )
        return redirect(url_for("site.dashboard"))
    questions = db.get_pool_questions_random(amount=PRACTICE_QUESTION_COUNT)

    session["practice"] = {
        "block_id": block_id,
        "question_ids": [q["id"] for q in questions],
        "index": 0,
        "correct_count": 0,
        "answered_count": 0,
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

    questions = db.list_pool_questions(None)
    by_id = {q["id"]: q for q in questions}
    qids = state["question_ids"]
    idx = state["index"]

    # Jump to a specific question number (1-based) via query param.
    jump_raw = (request.args.get("q") or "").strip()
    if jump_raw.isdigit():
        jump = int(jump_raw)
        if 1 <= jump <= len(qids):
            state["index"] = jump - 1
            state["last_feedback"] = None
            session["practice"] = state
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
        if action == "exit":
            session.pop("practice", None)
            return redirect(url_for("site.dashboard"))
        if action == "finish":
            total = len(qids)
            db.save_pool_attempt(
                session["user_id"], block_id, total,
                state["correct_count"], state.get("answered_count", 0),
            )
            session.pop("practice", None)
            flash("Esercitazione completata e salvata.", "success")
            return redirect(url_for("site.pool_history", block_id=block_id))
        if action == "prev":
            if state["index"] > 0:
                state["index"] -= 1
            state["last_feedback"] = None
            session["practice"] = state
            return redirect(url_for("site.practice_question", block_id=block_id))
        if action == "next":
            state["index"] += 1
            state["last_feedback"] = None
            session["practice"] = state
            if state["index"] >= len(qids):
                return redirect(url_for("site.practice_result", block_id=block_id))
            return redirect(url_for("site.practice_question", block_id=block_id))

        kind = (current.get("question_kind") or "single").strip().lower()
        if kind == "number":
            ans = (request.form.get("number_answer") or "").strip()
            if not ans or not ans.isdigit():
                flash("Inserisci solo numeri.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            correct = (current.get("correct_number") or "").strip()
            is_correct = ans == correct
            if is_correct:
                state["correct_count"] += 1
            state["last_feedback"] = {
                "kind": "number",
                "selected_number": ans,
                "correct_number": correct,
                "is_correct": is_correct,
            }
        elif kind in ("multi_one", "multi_many"):
            raw = request.form.getlist("selected_options")
            if not raw:
                flash("Seleziona almeno una risposta.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            try:
                selected = sorted({int(x) for x in raw})
            except ValueError:
                flash("Risposta non valida.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            if any(i not in (0, 1, 2, 3) for i in selected):
                flash("Risposta non valida.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            if kind == "multi_one" and len(selected) != 1:
                flash("Seleziona una sola risposta.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            correct = sorted({int(x) for x in (current.get("correct_options") or [])})
            is_correct = selected == correct
            if is_correct:
                state["correct_count"] += 1
            state["last_feedback"] = {
                "kind": kind,
                "selected_options": selected,
                "correct_options": correct,
                "is_correct": is_correct,
            }
        else:
            selected_raw = request.form.get("selected_option")
            if selected_raw is None:
                flash("Seleziona una risposta.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            try:
                selected_int = int(selected_raw)
            except ValueError:
                flash("Risposta non valida.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            if selected_int not in (0, 1, 2, 3):
                flash("Risposta non valida.", "error")
                return redirect(url_for("site.practice_question", block_id=block_id))
            is_correct = selected_int == int(current["correct_option"])
            if is_correct:
                state["correct_count"] += 1
            state["last_feedback"] = {
                "kind": "single",
                "selected_option": selected_int,
                "correct_option": int(current["correct_option"]),
                "is_correct": is_correct,
            }
        state["answered_count"] = state.get("answered_count", 0) + 1
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
    answered = state.get("answered_count", 0)
    percent = round((correct / total) * 100, 2) if total else 0
    db.save_pool_attempt(session["user_id"], block_id, total, correct, answered)
    session.pop("practice", None)
    flash("Esercitazione completata e salvata.", "success")
    return redirect(url_for("site.pool_history", block_id=block_id))


@site.get("/practice/<int:block_id>/history")
def pool_history(block_id: int):
    if not _participant_required():
        return redirect(url_for("site.login"))
    if block_id not in (2, 3, 4):
        return redirect(url_for("site.dashboard"))
    attempts = db.list_pool_attempts(session["user_id"], block_id)
    return render_template(
        "pool_history.html",
        block_id=block_id,
        attempts=attempts,
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

        if db.has_completed_attempt(session["user_id"], exam_session["id"]):
            flash("Hai già completato questo esame. Non è possibile rifarlo.", "error")
            return redirect(url_for("site.dashboard"))

        attempt = db.get_in_progress_attempt(session["user_id"], exam_session["id"])
        if not attempt:
            attempt = db.get_or_create_attempt(session["user_id"], exam_session["id"])

        # Random question order per participant attempt, stable for this session.
        ordered_ids = [q["id"] for q in questions]
        random.shuffle(ordered_ids)
        session["exam_attempt_id"] = attempt["id"]
        session["exam_position"] = 0
        session["exam_question_order"] = ordered_ids
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

    by_id = {q["id"]: q for q in questions}
    order = session.get("exam_question_order")
    if not order or len(order) != len(questions) or any(qid not in by_id for qid in order):
        order = [q["id"] for q in questions]
        random.shuffle(order)
        session["exam_question_order"] = order
    ordered_questions = [by_id[qid] for qid in order]

    remaining = _remaining_seconds(attempt, exam_session)
    if remaining == 0:
        db.finish_attempt(attempt_id)
        return redirect(url_for("site.exam_finished", attempt_id=attempt_id))

    pos = int(session.get("exam_position", 0))
    if pos < 0:
        pos = 0
    if pos >= len(ordered_questions):
        pos = len(ordered_questions) - 1
    current = ordered_questions[pos]
    existing = answers_map.get(current["id"])
    nav_items = []
    for i, q in enumerate(ordered_questions):
        ans = answers_map.get(q["id"])
        qk = (q.get("question_kind") or "single").strip().lower()
        if ans is None:
            answered = False
        elif qk == "number":
            answered = bool((ans.get("selected_number") or "").strip())
        elif qk == "multi_many":
            answered = bool(ans.get("selected_options"))
        else:
            answered = ans.get("selected_option") is not None
        nav_items.append(
            {
                "pos": i,
                "answered": answered,
                "standby": bool(ans.get("is_standby")) if ans else False,
            }
        )

    if request.method == "POST":
        action = request.form.get("action", "save_next")
        standby = bool(request.form.get("standby"))
        kind = (current.get("question_kind") or "single").strip().lower()

        selected = None
        selected_options = None
        selected_number = None

        if kind == "number":
            selected_number = (request.form.get("number_answer") or "").strip()
        elif kind == "multi_many":
            raw = request.form.getlist("selected_options")
            if raw:
                try:
                    selected_options = sorted({int(x) for x in raw})
                except ValueError:
                    pass
        else:
            selected_raw = request.form.get("selected_option")
            if selected_raw not in (None, ""):
                try:
                    selected = int(selected_raw)
                except ValueError:
                    pass
                else:
                    if selected not in (0, 1, 2, 3):
                        selected = None

        db.save_exam_answer(
            attempt_id,
            current["id"],
            selected,
            standby,
            selected_options=selected_options,
            selected_number=selected_number,
        )

        if action == "save_next":
            session["exam_position"] = min(pos + 1, len(ordered_questions) - 1)
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
        total=len(ordered_questions),
        answer=existing,
        remaining_seconds=remaining,
        nav_items=nav_items,
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

    by_id = {q["id"]: q for q in questions}
    order = session.get("exam_question_order")
    if not order or len(order) != len(questions) or any(qid not in by_id for qid in order):
        order = [q["id"] for q in questions]
        session["exam_question_order"] = order
    ordered_questions = [by_id[qid] for qid in order]

    rows = []
    unanswered = 0
    for i, q in enumerate(ordered_questions):
        ans = answers_map.get(q["id"])
        standby = bool(ans["is_standby"]) if ans else False
        qk = (q.get("question_kind") or "single").strip().lower()
        if ans is None:
            has_answer = False
        elif qk == "number":
            has_answer = bool((ans.get("selected_number") or "").strip())
        elif qk == "multi_many":
            has_answer = bool(ans.get("selected_options"))
        else:
            has_answer = ans.get("selected_option") is not None
        if not has_answer:
            unanswered += 1
        rows.append({"i": i, "q": q, "has_answer": has_answer, "standby": standby})

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
    session.pop("exam_question_order", None)
    return render_template("exam_finished.html", report=report)
