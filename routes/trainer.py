from __future__ import annotations

import os
import uuid
from functools import wraps

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

import db

trainer = Blueprint("trainer", __name__, url_prefix="/trainer")
EXAM_QUESTION_COUNT = 30
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def trainer_required(f):
    @wraps(f)
    def _wrapped(*args, **kwargs):
        if not session.get("trainer_id"):
            return redirect(url_for("trainer.login"))
        return f(*args, **kwargs)

    return _wrapped


def _save_uploaded_question_image(file_storage) -> tuple[str | None, str | None]:
    if not file_storage or not file_storage.filename:
        return None, None

    safe_name = secure_filename(file_storage.filename)
    if "." not in safe_name:
        return None, "Formato immagine non valido."

    ext = safe_name.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return None, "Formato immagine non supportato. Usa PNG/JPG/JPEG/GIF/WEBP."

    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "questions")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{ext}"
    abs_path = os.path.join(upload_dir, filename)
    file_storage.save(abs_path)
    return f"/static/uploads/questions/{filename}", None


def _redirect_trainer_pool():
    """Dopo POST su /pool, torna alla lista mantenendo pagina e ordinamento."""
    page_raw = (request.form.get("page") or request.args.get("page") or "1").strip()
    sort_by = (request.form.get("sort_by") or request.args.get("sort_by") or "question_number").strip().lower()
    sort_dir = (request.form.get("sort_dir") or request.args.get("sort_dir") or "asc").strip().lower()
    allowed_sort = {"question_number", "question_text", "correct_option"}
    if sort_by not in allowed_sort:
        sort_by = "question_number"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"
    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1
    return redirect(url_for("trainer.pool", page=page, sort_by=sort_by, sort_dir=sort_dir))


def _pool_pagination_entries(page: int, total_pages: int) -> list[int | str]:
    """Numeri di pagina e 'ellipsis' per la UI (stile elenco con salti)."""
    if total_pages <= 1:
        return []
    if total_pages <= 11:
        return list(range(1, total_pages + 1))
    p = max(1, min(page, total_pages))
    out: list[int | str] = []
    if p <= 5:
        for i in range(1, min(6, total_pages + 1)):
            out.append(i)
        if total_pages > 5 and out[-1] != total_pages:
            out.append("ellipsis")
            out.append(total_pages)
        return out
    if p >= total_pages - 3:
        out.append(1)
        out.append("ellipsis")
        start = max(2, total_pages - 4)
        for i in range(start, total_pages + 1):
            out.append(i)
        return out
    out.append(1)
    out.append("ellipsis")
    for i in range(p - 1, p + 2):
        out.append(i)
    out.append("ellipsis")
    out.append(total_pages)
    return out


@trainer.route("/login", methods=["GET", "POST"])
def login():
    return redirect(url_for("site.login"))


@trainer.get("/logout")
def logout():
    session.pop("trainer_id", None)
    session.pop("trainer_name", None)
    session.pop("trainer_is_admin", None)
    flash("Logout effettuato.", "success")
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
            flash("La password esame viene gestita solo tramite generazione automatica.", "error")
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
        if action == "delete_question":
            qid_raw = (request.form.get("question_id") or "").strip()
            if not qid_raw.isdigit():
                flash("Domanda non valida.", "error")
                return _redirect_trainer_pool()
            if db.delete_pool_question(int(qid_raw)):
                flash("Domanda eliminata.", "success")
            else:
                flash("Domanda non trovata.", "error")
            return _redirect_trainer_pool()

        question_kind = (request.form.get("question_kind") or "single").strip().lower()
        if question_kind not in ("number", "single", "multi_one", "multi_many"):
            question_kind = "single"

        block_raw = (request.form.get("block_id") or "auto").strip().lower()
        if action == "update_question":
            if not block_raw.isdigit():
                flash("Blocco non valido.", "error")
                return _redirect_trainer_pool()
            block_id = int(block_raw)
        else:
            if block_raw == "auto":
                block_id = db.get_auto_pool_block_id()
            elif block_raw.isdigit():
                block_id = int(block_raw)
            else:
                flash("Blocco non valido.", "error")
                return _redirect_trainer_pool()

        question_text = (request.form.get("question_text") or "").strip()
        existing_image_url = (request.form.get("existing_image_url") or "").strip() or None
        uploaded_image_url, upload_error = _save_uploaded_question_image(
            request.files.get("image_file")
        )
        if upload_error:
            flash(upload_error, "error")
            return _redirect_trainer_pool()
        image_url = uploaded_image_url
        options = [
            (request.form.get("opt0") or "").strip(),
            (request.form.get("opt1") or "").strip(),
            (request.form.get("opt2") or "").strip(),
            (request.form.get("opt3") or "").strip(),
        ]

        correct_options: list[int] = []
        correct_number = None
        if question_kind == "number":
            correct_number = (request.form.get("correct_number") or "").strip()
            if not correct_number or not correct_number.isdigit():
                flash("Inserisci un numero valido come risposta corretta.", "error")
                return _redirect_trainer_pool()
        else:
            raw_list = request.form.getlist("correct_options")
            # fallback for legacy single-choice radios
            if not raw_list:
                raw_one = (request.form.get("correct_option") or "").strip()
                if raw_one:
                    raw_list = [raw_one]
            try:
                correct_options = [int(x) for x in raw_list]
            except ValueError:
                flash("Risposta corretta non valida.", "error")
                return _redirect_trainer_pool()
            correct_options = sorted(set(correct_options))
            if any(i not in (0, 1, 2, 3) for i in correct_options):
                flash("Risposta corretta non valida.", "error")
                return _redirect_trainer_pool()
            if question_kind in ("single", "multi_one") and len(correct_options) != 1:
                flash("Seleziona una sola risposta corretta.", "error")
                return _redirect_trainer_pool()
            if question_kind == "multi_many" and len(correct_options) < 1:
                flash("Seleziona almeno una risposta corretta.", "error")
                return _redirect_trainer_pool()
            if not question_text or any(not o for o in options):
                flash("Compila correttamente la domanda.", "error")
                return _redirect_trainer_pool()

        if block_id not in (2, 3, 4) or not question_text:
            flash("Compila correttamente la domanda.", "error")
            return _redirect_trainer_pool()

        if action == "update_question":
            qid_raw = request.form.get("question_id", "").strip()
            if not qid_raw.isdigit():
                flash("ID domanda non valido.", "error")
                return _redirect_trainer_pool()
            qid = int(qid_raw)
            if not db.get_pool_question(qid):
                flash("Domanda non trovata.", "error")
                return _redirect_trainer_pool()
            if not image_url:
                image_url = existing_image_url
            try:
                db.update_pool_question_typed(
                    qid,
                    block_id,
                    question_text,
                    image_url,
                    question_kind,
                    None if question_kind == "number" else options,
                    None if question_kind == "number" else correct_options,
                    correct_number,
                )
            except ValueError:
                flash("Compila correttamente la domanda.", "error")
                return _redirect_trainer_pool()
            flash("Domanda aggiornata.", "success")
            return _redirect_trainer_pool()

        if db.count_pool_questions_total() >= 150:
            flash("Limite raggiunto: il pool contiene già 150 domande.", "error")
            return _redirect_trainer_pool()

        try:
            db.create_pool_question_typed(
                block_id,
                question_text,
                image_url,
                question_kind,
                None if question_kind == "number" else options,
                None if question_kind == "number" else correct_options,
                correct_number,
            )
        except ValueError:
            flash("Compila correttamente la domanda.", "error")
            return _redirect_trainer_pool()
        flash("Domanda inserita.", "success")
        return _redirect_trainer_pool()

    all_for_block = db.list_pool_questions()
    sort_by = (request.args.get("sort_by") or "question_number").strip().lower()
    sort_dir = (request.args.get("sort_dir") or "asc").strip().lower()
    allowed_sort = {"question_number", "question_text", "correct_option"}
    if sort_by not in allowed_sort:
        sort_by = "question_number"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"
    reverse = sort_dir == "desc"

    def _pool_sort_key(q: dict):
        if sort_by == "question_number":
            n = q.get("question_number")
            return (10**9 if n is None else int(n), q.get("id") or 0)
        if sort_by == "question_text":
            return (q.get("question_text") or "").lower()
        if sort_by == "correct_option":
            return q.get("correct_option") if q.get("correct_option") is not None else -1
        n = q.get("question_number")
        return (10**9 if n is None else int(n), q.get("id") or 0)

    all_for_block = sorted(all_for_block, key=_pool_sort_key, reverse=reverse)

    total_questions = len(all_for_block)
    page_size = 15
    page_raw = request.args.get("page", "1").strip()
    page = int(page_raw) if page_raw.isdigit() else 1
    if page < 1:
        page = 1
    total_pages = max((total_questions + page_size - 1) // page_size, 1)
    if page > total_pages:
        page = total_pages
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    questions = all_for_block[start_idx:end_idx]
    return render_template(
        "trainer_pool.html",
        questions=questions,
        total_questions=total_questions,
        page=page,
        total_pages=total_pages,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
        pagination_entries=_pool_pagination_entries(page, total_pages),
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

        if action == "update_session":
            active = db.get_active_exam_session()
            if not active:
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))
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
            db.update_exam_session(active["id"], title, duration_int)
            flash("Sessione aggiornata.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "add_question":
            active = db.get_active_exam_session()
            if not active:
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))
            current_questions = db.list_exam_questions(active["id"])
            if len(current_questions) >= EXAM_QUESTION_COUNT:
                flash(
                    f"La sessione attiva ha gia' {EXAM_QUESTION_COUNT} domande.",
                    "error",
                )
                return redirect(url_for("trainer.exam"))
            position = max((q["position"] for q in current_questions), default=0) + 1
            points = 1

            question_kind = (request.form.get("question_kind") or "single").strip().lower()
            if question_kind not in ("number", "single", "multi_many"):
                question_kind = "single"

            question_text = (request.form.get("question_text") or "").strip()
            uploaded_image_url, upload_error = _save_uploaded_question_image(
                request.files.get("image_file")
            )
            if upload_error:
                flash(upload_error, "error")
                return redirect(url_for("trainer.exam"))
            image_url = uploaded_image_url

            options = []
            correct_option = 0
            correct_options: list[int] = []
            correct_number = None

            if question_kind == "number":
                correct_number = (request.form.get("correct_number") or "").strip()
                if not correct_number or not correct_number.isdigit():
                    flash("Inserisci un numero valido come risposta corretta.", "error")
                    return redirect(url_for("trainer.exam"))
            else:
                options = [
                    (request.form.get("opt0") or "").strip(),
                    (request.form.get("opt1") or "").strip(),
                    (request.form.get("opt2") or "").strip(),
                    (request.form.get("opt3") or "").strip(),
                ]
                if not question_text or any(not o for o in options):
                    flash("Compila la domanda e tutte le opzioni.", "error")
                    return redirect(url_for("trainer.exam"))
                if question_kind == "multi_many":
                    raw_list = request.form.getlist("correct_options")
                    if not raw_list:
                        raw_one = (request.form.get("correct_option") or "").strip()
                        if raw_one:
                            raw_list = [raw_one]
                    try:
                        correct_options = sorted({int(x) for x in raw_list})
                    except ValueError:
                        flash("Risposta corretta non valida.", "error")
                        return redirect(url_for("trainer.exam"))
                    if not correct_options or any(i not in (0, 1, 2, 3) for i in correct_options):
                        flash("Seleziona almeno una risposta corretta.", "error")
                        return redirect(url_for("trainer.exam"))
                    correct_option = correct_options[0]
                else:
                    raw_co = (request.form.get("correct_option") or "").strip()
                    try:
                        correct_option = int(raw_co)
                    except ValueError:
                        flash("Risposta corretta non valida.", "error")
                        return redirect(url_for("trainer.exam"))
                    if correct_option not in (0, 1, 2, 3):
                        flash("Risposta corretta non valida.", "error")
                        return redirect(url_for("trainer.exam"))
                    correct_options = [correct_option]

            if not question_text:
                flash("Compila il testo della domanda.", "error")
                return redirect(url_for("trainer.exam"))

            db.create_exam_question(
                active["id"],
                position,
                question_text,
                image_url,
                options,
                correct_option,
                points,
                question_kind=question_kind,
                correct_options=correct_options if question_kind != "number" else None,
                correct_number=correct_number,
            )
            flash("Domanda esame aggiunta.", "success")
            return redirect(url_for("trainer.exam"))

        if action == "move_question":
            is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
            active = db.get_active_exam_session()
            if not active:
                if is_ajax:
                    return jsonify(ok=False), 400
                flash("Nessuna sessione attiva.", "error")
                return redirect(url_for("trainer.exam"))
            qid_raw = request.form.get("question_id", "").strip()
            direction = request.form.get("direction", "").strip()
            if not qid_raw.isdigit() or direction not in ("up", "down"):
                if is_ajax:
                    return jsonify(ok=False), 400
                return redirect(url_for("trainer.exam"))
            qid = int(qid_raw)
            questions = db.list_exam_questions(active["id"])
            idx = next((i for i, q in enumerate(questions) if q["id"] == qid), None)
            if idx is None:
                if is_ajax:
                    return jsonify(ok=False), 400
                return redirect(url_for("trainer.exam"))
            swap_idx = idx - 1 if direction == "up" else idx + 1
            if 0 <= swap_idx < len(questions):
                db.swap_exam_question_positions(questions[idx]["id"], questions[swap_idx]["id"])
            if is_ajax:
                return jsonify(ok=True)
            return redirect(url_for("trainer.exam") + f"#q-{qid}")

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
            db.reorder_exam_questions(active["id"])
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

            position = current["position"]
            points = current["points"]

            question_kind = (request.form.get("question_kind") or "single").strip().lower()
            if question_kind not in ("number", "single", "multi_many"):
                question_kind = "single"

            question_text = (request.form.get("question_text") or "").strip()
            existing_image_url = (request.form.get("existing_image_url") or "").strip() or None
            uploaded_image_url, upload_error = _save_uploaded_question_image(
                request.files.get("image_file")
            )
            if upload_error:
                flash(upload_error, "error")
                return redirect(url_for("trainer.exam"))
            image_url = uploaded_image_url or existing_image_url

            options = []
            correct_option = 0
            correct_options: list[int] = []
            correct_number = None

            if question_kind == "number":
                correct_number = (request.form.get("correct_number") or "").strip()
                if not correct_number or not correct_number.isdigit():
                    flash("Inserisci un numero valido come risposta corretta.", "error")
                    return redirect(url_for("trainer.exam"))
            else:
                options = [
                    (request.form.get("opt0") or "").strip(),
                    (request.form.get("opt1") or "").strip(),
                    (request.form.get("opt2") or "").strip(),
                    (request.form.get("opt3") or "").strip(),
                ]
                if not question_text or any(not o for o in options):
                    flash("Compila la domanda e tutte le opzioni.", "error")
                    return redirect(url_for("trainer.exam"))
                if question_kind == "multi_many":
                    raw_list = request.form.getlist("correct_options")
                    if not raw_list:
                        raw_one = (request.form.get("correct_option") or "").strip()
                        if raw_one:
                            raw_list = [raw_one]
                    try:
                        correct_options = sorted({int(x) for x in raw_list})
                    except ValueError:
                        flash("Risposta corretta non valida.", "error")
                        return redirect(url_for("trainer.exam"))
                    if not correct_options or any(i not in (0, 1, 2, 3) for i in correct_options):
                        flash("Seleziona almeno una risposta corretta.", "error")
                        return redirect(url_for("trainer.exam"))
                    correct_option = correct_options[0]
                else:
                    raw_co = (request.form.get("correct_option") or "").strip()
                    try:
                        correct_option = int(raw_co)
                    except ValueError:
                        flash("Risposta corretta non valida.", "error")
                        return redirect(url_for("trainer.exam"))
                    if correct_option not in (0, 1, 2, 3):
                        flash("Risposta corretta non valida.", "error")
                        return redirect(url_for("trainer.exam"))
                    correct_options = [correct_option]

            if not question_text:
                flash("Compila il testo della domanda.", "error")
                return redirect(url_for("trainer.exam"))

            db.update_exam_question(
                qid,
                position,
                question_text,
                image_url,
                options,
                correct_option,
                points,
                question_kind=question_kind,
                correct_options=correct_options if question_kind != "number" else None,
                correct_number=correct_number,
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
