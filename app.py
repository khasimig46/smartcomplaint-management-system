import os

from flask import Flask, render_template

from routes.auth_routes import bp as auth_bp
from routes.complaint_routes import bp
from services.auth import seed_admin_from_env


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)
    seed_admin_from_env()

    @app.get("/")
    def index():
        return render_template("complaint_form.html")

    @app.get("/login")
    def login_page():
        return render_template("login.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
