import os

from flask import Flask

from db import init_db, seed_demo_data
from routes.site import site
from routes.trainer import trainer
from routes.admin import admin


def _swiss_date(value):
    if not value:
        return "-"
    s = str(value).replace("T", " ").strip()
    try:
        parts = s.split(" ")
        ymd = parts[0].split("-")
        hm = parts[1][:5] if len(parts) > 1 else ""
        result = f"{ymd[2]}.{ymd[1]}.{ymd[0]}"
        if hm:
            result += f" {hm}"
        return result
    except Exception:
        return s


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    app.jinja_env.filters["swiss_date"] = _swiss_date

    uploads_dir = os.path.join(app.root_path, "static", "uploads", "questions")
    os.makedirs(uploads_dir, exist_ok=True)

    app.register_blueprint(site)
    app.register_blueprint(trainer)
    app.register_blueprint(admin)

    init_db()
    seed_demo_data()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5002)
