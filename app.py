from flask import Flask, render_template

from routes.complaint_routes import bp


def create_app():
    app = Flask(__name__)
    app.register_blueprint(bp)

    @app.get("/")
    def index():
        return render_template("complaint_form.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
