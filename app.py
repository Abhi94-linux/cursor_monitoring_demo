"""Local demo shell for Linux server monitoring."""

import os
import secrets
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parent
AUTH_ERROR = "Invalid username or password."


def require_settings(env):
    """Return the session key and password hash, or refuse to start."""
    secret = (env.get("SECRET_KEY") or "").strip()
    password_hash = (env.get("ADMIN_PASSWORD_HASH") or "").strip()
    if not secret or not password_hash:
        raise SystemExit("Set SECRET_KEY and ADMIN_PASSWORD_HASH in .env before starting.")
    return secret, password_hash


def create_app(secret_key, password_hash):
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config["ADMIN_PASSWORD_HASH"] = password_hash
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("user") != "admin":
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapped

    @app.get("/")
    @login_required
    def index():
        return render_template("index.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("user") == "admin":
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if _password_matches(username, password, app.config["ADMIN_PASSWORD_HASH"]):
                session.clear()
                session["user"] = "admin"
                return redirect(url_for("index"))
            error = AUTH_ERROR
        return render_template("login.html", error=error), (401 if error else 200)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    return app


def _password_matches(username, password, password_hash):
    if not isinstance(username, str) or not isinstance(password, str):
        return False
    user_ok = secrets.compare_digest(username.strip(), "admin")
    try:
        password_ok = bool(password_hash) and check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False
    return user_ok and password_ok


def main():
    load_dotenv(ROOT / ".env")
    secret, password_hash = require_settings(os.environ)
    create_app(secret, password_hash).run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
