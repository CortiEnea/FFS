from __future__ import annotations

from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

import db

admin = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def _wrapped(*args, **kwargs):
        if not session.get("trainer_id") or not session.get("trainer_is_admin"):
            flash("Accesso non autorizzato.", "error")
            return redirect(url_for("site.login"))
        return f(*args, **kwargs)

    return _wrapped


@admin.get("/logout")
def logout():
    return redirect(url_for("trainer.logout"))


@admin.route("/users", methods=["GET", "POST"])
@admin_required
def users():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()

        if action == "create_user":
            role = (request.form.get("role") or "participant").strip().lower()
            username = (request.form.get("username") or "").strip().lower()
            full_name = (request.form.get("full_name") or "").strip()
            password = request.form.get("password") or ""

            if role not in ("participant", "trainer"):
                flash("Ruolo non valido.", "error")
                return redirect(url_for("admin.users"))
            if not username or len(username) < 3:
                flash("Username troppo corto (minimo 3 caratteri).", "error")
                return redirect(url_for("admin.users"))
            if not full_name:
                flash("Nome obbligatorio.", "error")
                return redirect(url_for("admin.users"))
            if len(password) < 6:
                flash("La password deve avere almeno 6 caratteri.", "error")
                return redirect(url_for("admin.users"))

            try:
                if role == "trainer":
                    db.create_trainer(
                        username, full_name, generate_password_hash(password), password
                    )
                else:
                    db.create_participant(
                        username, full_name, generate_password_hash(password), password
                    )
            except Exception:
                flash("Username già presente.", "error")
                return redirect(url_for("admin.users"))

            flash("Utente creato.", "success")
            return redirect(url_for("admin.users"))

        if action == "delete_user":
            user_id_raw = (request.form.get("user_id") or "").strip()
            if not user_id_raw.isdigit():
                flash("Utente non valido.", "error")
                return redirect(url_for("admin.users"))
            uid = int(user_id_raw)
            if uid == int(session.get("trainer_id") or 0):
                flash("Non puoi eliminare il tuo utente.", "error")
                return redirect(url_for("admin.users"))
            if db.delete_user(uid):
                flash("Utente eliminato.", "success")
            else:
                flash("Utente non eliminabile.", "error")
            return redirect(url_for("admin.users"))

        flash("Azione non valida.", "error")
        return redirect(url_for("admin.users"))

    return render_template(
        "admin_users.html",
        participants=db.list_participants(),
        trainers=db.list_trainers(),
        admins=db.list_admins(),
    )

