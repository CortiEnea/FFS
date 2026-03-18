from __future__ import annotations

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

import db

trainer = Blueprint("trainer", __name__, url_prefix="/trainer")
EXAM_QUESTION_COUNT = 30


def trainer_required(f):
    @wraps(f)
    def _wrapped(*args, **kwargs):
        if not session.get("trainer_id"):
            return redirect(url_for("trainer.login"))
        return f(*args, **kwargs)

    return _wrapped


@trainer.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("site.login"))


@trainer.get("/logout")
def logout():
    session.pop("trainer_id", None)
    session.pop("trainer_name", None)
    flash("Logout formatore effettuato.", "success")
    return redirect(url_for("trainer.login"))


@trainer.get("/")
@trainer_required
def dashboard():
    active_session = db.get_active_exam_session()
    sessions = db.list_exam_sessions()
    participants = db.list_participants()
    reports = db.list_completed_attempts()
    pool_counts = {
        2: db.count_pool_questions(2),
        3: db.count_pool_questions(3),
        4: db.count_pool_questions(4),
    }
    active_exam_count = db.count_exam_questions(active_session["id"]) if active_session else 0
    return render_template(
        "trainer_dashboard.html",
        active_session=active_session,
        sessions=sessions,
        participants=participants,
        reports=reports,
        pool_counts=pool_counts,
        active_exam_count=active_exam_count,
        required_exam_count=EXAM_QUESTION_COUNT,
    )


@trainer.route("/participants", methods=["GET", "POST"])
@trainer_required
def participants():
    active_session = db.get_active_exam_session()
    if request.method == "POST":
        action = request.form.get("action", "create_participant")
        if action == "create_participant":
            username = (request.form.get("username") or "").strip().lower()
            full_name = (request.form.get("full_name") or "").strip()
            password = request.form.get("password") or ""

            if not all([username, full_name, password]):
                flash("Compila tutti i campi.", "error")
                return redirect(url_for("trainer.participants"))
            if len(username) < 3:
                flash("Username troppo corto (minimo 3 caratteri).", "error")
                return redirect(url_for("trainer.participants"))
            if len(password) < 6:
                flash("La password di accesso deve avere almeno 6 caratteri.", "error")
                return redirect(url_for("trainer.participants"))

            try:
                db.create_participant(
                    username,
                    full_name,
                    generate_password_hash(password),
                    password,
                )
            except Exception:
                flash("Username gia' presente.", "error")
                return redirect(url_for("trainer.participants"))

            flash("Partecipante creato.", "success")
            return redirect(url_for("trainer.participants"))

        if action == "update_access_password":
            user_id_raw = (request.form.get("user_id") or "").strip()
            password = request.form.get("new_access_password") or ""
            if not user_id_raw.isdigit():
                flash("Partecipante non valido.", "error")
                return redirect(url_for("trainer.participants"))
            if len(password) < 6:
                flash("La password di accesso deve avere almeno 6 caratteri.", "error")
                return redirect(url_for("trainer.participants"))
            db.update_participant_access_password(int(user_id_raw), password)
            flash("Password di accesso aggiornata.", "success")
            return redirect(url_for("trainer.participants"))

        if action == "update_exam_password":
            if not active_session:
                flash("Nessuna sessione esame attiva.", "error")
                return redirect(url_for("trainer.participants"))
            user_id_raw = (request.form.get("user_id") or "").strip()
            password = request.form.get("new_exam_password") or ""
            if not user_id_raw.isdigit():
                flash("Partecipante non valido.", "error")
                return redirect(url_for("trainer.participants"))
            if len(password) < 4:
                flash("La password esame deve avere almeno 4 caratteri.", "error")
                return redirect(url_for("trainer.participants"))
            db.set_session_exam_password(active_session["id"], int(user_id_raw), password)
            flash("Password esame della sessione aggiornata.", "success")
            return redirect(url_for("trainer.participants"))

        if action == "generate_exam_password":
            if not active_session:
                flash("Nessuna sessione esame attiva.", "error")
                return redirect(url_for("trainer.participants"))
            user_id_raw = (request.form.get("user_id") or "").strip()
            username = (request.form.get("username") or "").strip().lower()
            if not user_id_raw.isdigit():
                flash("Partecipante non valido.", "error")
                return redirect(url_for("trainer.participants"))
            generated = db.generate_exam_password(username)
            db.set_session_exam_password(active_session["id"], int(user_id_raw), generated)
            flash(f"Nuova password esame generata: {generated}", "success")
            return redirect(url_for("trainer.participants"))

        if action == "delete_participant":
            user_id_raw = (request.form.get("user_id") or "").strip()
            if not user_id_raw.isdigit():
                flash("Partecipante non valido.", "error")
                return redirect(url_for("trainer.participants"))
            db.delete_participant(int(user_id_raw))
            flash("Partecipante eliminato.", "success")
            return redirect(url_for("trainer.participants"))

        flash("Azione non valida.", "error")
        return redirect(url_for("trainer.participants"))

    session_credentials = (
        db.list_session_participant_credentials(active_session["id"]) if active_session else {}
    )
    return render_template(
        "trainer_participants.html",
        participants=db.list_participants(),
        active_session=active_session,
        session_credentials=session_credentials,
    )


@trainer.route("/pool", methods=["GET", "POST"])
@trainer_required
def pool():
    if request.method == "POST":
        action = request.form.get("action", "create_question")
        try:
            block_id = int(request.form.get("block_id", "0"))
            correct_option = int(request.form.get("correct_option", "-1"))
        except ValueError:
            flash("Dati non validi.", "error")
            return redirect(url_for("trainer.pool"))

        question_text = (request.form.get("question_text") or "").strip()
        options = [
            (request.form.get("opt0") or "").strip(),
            (request.form.get("opt1") or "").strip(),
            (request.form.get("opt2") or "").strip(),
            (request.form.get("opt3") or "").strip(),
        ]
        if block_id not in (2, 3, 4) or not question_text or any(not o for o in options):
            flash("Compila correttamente la domanda.", "error")
            return redirect(url_for("trainer.pool"))
        if correct_option not in (0, 1, 2, 3):
            flash("Risposta corretta non valida.", "error")
            return redirect(url_for("trainer.pool"))

        if action == "update_question":
            qid_raw = request.form.get("question_id", "").strip()
            if not qid_raw.isdigit():
                flash("ID domanda non valido.", "error")
                return redirect(url_for("trainer.pool", block=block_id))
            qid = int(qid_raw)
            if not db.get_pool_question(qid):
                flash("Domanda non trovata.", "error")
                return redirect(url_for("trainer.pool", block=block_id))
            db.update_pool_question(qid, block_id, question_text, options, correct_option)
            flash("Domanda aggiornata.", "success")
            return redirect(url_for("trainer.pool", block=block_id))

        db.create_pool_question(block_id, question_text, options, correct_option)
        flash("Domanda inserita.", "success")
        return redirect(url_for("trainer.pool"))

    selected_block = request.args.get("block")
    block_id = int(selected_block) if selected_block and selected_block.isdigit() else None
    all_for_block = db.list_pool_questions(block_id) if block_id else []
    show_limit = 30
    questions = all_for_block[:show_limit] if block_id else []
    hidden_count = max(len(all_for_block) - len(questions), 0)
    pool_counts = {
        2: db.count_pool_questions(2),
        3: db.count_pool_questions(3),
        4: db.count_pool_questions(4),
    }
    pool_previews = {
        2: db.list_pool_questions(2)[:4],
        3: db.list_pool_questions(3)[:4],
        4: db.list_pool_questions(4)[:4],
    }
    return render_template(
        "trainer_pool.html",
        questions=questions,
        selected_block=block_id,
        pool_counts=pool_counts,
        pool_previews=pool_previews,
        hidden_count=hidden_count,
        show_limit=show_limit,
    )


@trainer.route("/exam", methods=["GET", "POST"])
@trainer_required
def exam():
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "create_session":
            title = (request.form.get("title") or "").strip()
            duration = request.form.get("duration_minutes", "30").strip()
            try:
                duration_int = int(duration)
            except ValueError:
                flash("Durata non valida.", "error")
                return redirect(url_for("trainer.exam"))
            if len(title) < 3 or duration_int <= 0:
                flash("Titolo o durata non validi.", "error")
                return redirect(url_for("trainer.exam"))
            db.create_exam_session(title, duration_int, activate=True)
            flash("Sessione creata e attivata.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "activate_session":
            session_id = request.form.get("session_id", "0")
            if not session_id.isdigit():
                flash("Sessione non valida.", "error")
                return redirect(url_for("trainer.exam"))
            db.set_active_exam_session(int(session_id))
            flash("Sessione attivata.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "add_question":
            active = db.get_active_exam_session()
            if not active:
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))
            current_count = db.count_exam_questions(active["id"])
            if current_count >= EXAM_QUESTION_COUNT:
                flash(
                    f"La sessione attiva ha gia' {EXAM_QUESTION_COUNT} domande.",
                    "error",
                )
                return redirect(url_for("trainer.exam"))
            try:
                position = int(request.form.get("position", "1"))
                correct_option = int(request.form.get("correct_option", "-1"))
                points = int(request.form.get("points", "1"))
            except ValueError:
                flash("Valori numerici non validi.", "error")
                return redirect(url_for("trainer.exam"))

            question_text = (request.form.get("question_text") or "").strip()
            options = [
                (request.form.get("opt0") or "").strip(),
                (request.form.get("opt1") or "").strip(),
                (request.form.get("opt2") or "").strip(),
                (request.form.get("opt3") or "").strip(),
            ]
            if not question_text or any(not o for o in options):
                flash("Compila la domanda e tutte le opzioni.", "error")
                return redirect(url_for("trainer.exam"))
            if correct_option not in (0, 1, 2, 3):
                flash("Risposta corretta non valida.", "error")
                return redirect(url_for("trainer.exam"))
            if position <= 0 or points <= 0:
                flash("Posizione e punti devono essere > 0.", "error")
                return redirect(url_for("trainer.exam"))
            if db.exam_question_position_exists(active["id"], position):
                flash("Posizione gia' usata in questa sessione.", "error")
                return redirect(url_for("trainer.exam"))

            db.create_exam_question(
                active["id"], position, question_text, options, correct_option, points
            )
            flash("Domanda esame aggiunta.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "delete_question":
            active = db.get_active_exam_session()
            if not active:
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))

            qid_raw = request.form.get("question_id", "").strip()
            if not qid_raw.isdigit():
                flash("ID domanda non valido.", "error")
                return redirect(url_for("trainer.exam"))
            qid = int(qid_raw)
            current = db.get_exam_question(qid)
            if not current:
                flash("Domanda non trovata.", "error")
                return redirect(url_for("trainer.exam"))
            if current["session_id"] != active["id"]:
                flash("Puoi cancellare solo domande della sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))

            db.delete_exam_question(qid)
            flash("Domanda esame eliminata.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "update_question":
            active = db.get_active_exam_session()
            if not active:
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))

            qid_raw = request.form.get("question_id", "").strip()
            if not qid_raw.isdigit():
                flash("ID domanda non valido.", "error")
                return redirect(url_for("trainer.exam"))
            qid = int(qid_raw)
            current = db.get_exam_question(qid)
            if not current:
                flash("Domanda non trovata.", "error")
                return redirect(url_for("trainer.exam"))
            if current["session_id"] != active["id"]:
                flash("Puoi modificare solo le domande della sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))

            try:
                position = int(request.form.get("position", "1"))
                correct_option = int(request.form.get("correct_option", "-1"))
                points = int(request.form.get("points", "1"))
            except ValueError:
                flash("Valori numerici non validi.", "error")
                return redirect(url_for("trainer.exam"))

            question_text = (request.form.get("question_text") or "").strip()
            options = [
                (request.form.get("opt0") or "").strip(),
                (request.form.get("opt1") or "").strip(),
                (request.form.get("opt2") or "").strip(),
                (request.form.get("opt3") or "").strip(),
            ]
            if not question_text or any(not o for o in options):
                flash("Compila la domanda e tutte le opzioni.", "error")
                return redirect(url_for("trainer.exam"))
            if correct_option not in (0, 1, 2, 3):
                flash("Risposta corretta non valida.", "error")
                return redirect(url_for("trainer.exam"))
            if position <= 0 or points <= 0:
                flash("Posizione e punti devono essere > 0.", "error")
                return redirect(url_for("trainer.exam"))
            if db.exam_question_position_exists(active["id"], position, exclude_question_id=qid):
                flash("Posizione gia' usata in questa sessione.", "error")
                return redirect(url_for("trainer.exam"))

            db.update_exam_question(
                qid,
                position,
                question_text,
                options,
                correct_option,
                points,
            )
            flash("Domanda esame aggiornata.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "save_participants":
            active = db.get_active_exam_session()
            if not active:
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))
            selected = []
            for raw in request.form.getlist("allowed_user_ids"):
                if raw.isdigit():
                    selected.append(int(raw))
            db.save_exam_session_participants(active["id"], selected)
            flash("Lista partecipanti aggiornata.", "success")
            return redirect(url_for("trainer.exam"))

    active_session = db.get_active_exam_session()
    sessions = db.list_exam_sessions()
    questions = db.list_exam_questions(active_session["id"]) if active_session else []
    participants = db.list_participants()
    allowed_map = (
        db.list_exam_session_participants_map(active_session["id"]) if active_session else {}
    )
    session_credentials = (
        db.list_session_participant_credentials(active_session["id"]) if active_session else {}
    )
    return render_template(
        "trainer_exam.html",
        active_session=active_session,
        sessions=sessions,
        questions=questions,
        required_exam_count=EXAM_QUESTION_COUNT,
        participants=participants,
        allowed_map=allowed_map,
        session_credentials=session_credentials,
    )


@trainer.get("/reports")
@trainer_required
def reports():
    rows = db.list_completed_attempts()
    return render_template("trainer_reports.html", rows=rows)


@trainer.get("/reports/<int:attempt_id>")
@trainer_required
def report_detail(attempt_id: int):
    report = db.build_attempt_report(attempt_id)
    if not report:
        flash("Report non trovato.", "error")
        return redirect(url_for("trainer.reports"))
    return render_template("trainer_report_detail.html", report=report)
