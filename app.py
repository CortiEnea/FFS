import os

from flask import Flask

from db import init_db, seed_demo_data
from routes.site import site
from routes.trainer import trainer


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret-change-me")

    app.register_blueprint(site)
    app.register_blueprint(trainer)

    init_db()
    seed_demo_data()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5002)
