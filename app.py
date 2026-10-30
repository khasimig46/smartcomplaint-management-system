import os

from flask import Flask, render_template

from routes.auth_routes import bp as auth_bp
from routes.complaint_routes import bp
from routes.dashboard_routes import bp as dashboard_bp
from routes.sla_routes import bp as sla_bp, start_monitor
from services.auth import seed_admin_from_env


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
    app.register_blueprint(auth_bp)
    app.register_blueprint(bp)
    app.register_blueprint(sla_bp)
    app.register_blueprint(dashboard_bp)
    seed_admin_from_env()

    @app.get("/")
    def index():
        return render_template("complaint_form.html")

    @app.get("/track")
    def track_page():
        return render_template("track.html")

    @app.get("/login")
    def login_page():
        return render_template("login.html")

    return app


app = create_app()

if __name__ == "__main__":
    start_monitor(app)  # background SLA checks every 60 s
    app.run(debug=True, use_reloader=False)
