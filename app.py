"""Local demo for Linux server monitoring."""

import logging
import os
import re
import secrets
import tempfile
import threading
import time
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from collector import collect
from poller import poll_loop, poll_server
from store import Store, demo_server_path, fullest_disk

ROOT = Path(__file__).resolve().parent
AUTH_ERROR = "Invalid username or password."
HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
USER_RE = re.compile(r"^[A-Za-z0-9._@+-]{1,64}$")
ID_RE = re.compile(r"^[a-f0-9]{32}$")
logger = logging.getLogger("monitor")


def _plain(value):
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def require_settings(env):
    """Return the session key and password hash, or refuse to start."""
    secret = _plain(env.get("SECRET_KEY"))
    password_hash = _plain(env.get("ADMIN_PASSWORD_HASH"))
    if not secret or not password_hash:
        raise SystemExit("Set SECRET_KEY and ADMIN_PASSWORD_HASH in .env before starting.")
    return secret, password_hash


def create_app(secret_key, password_hash, store=None):
    app = Flask(__name__)
    app.secret_key = secret_key
    app.config["ADMIN_PASSWORD_HASH"] = password_hash
    app.config["STORE"] = store if store is not None else Store(_empty_store_path())
    app.config["POLL_ON_ADD"] = False
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=64 * 1024,
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
        rows = []
        for row in app.config["STORE"].rows():
            latest = row["latest"]
            disk = fullest_disk(latest["disks"]) if latest else None
            rows.append({**row, "disk": disk})
        return render_template("servers.html", rows=rows, csrf_token=_csrf_token())

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

    @app.route("/servers/add", methods=["GET", "POST"])
    @login_required
    def add_server():
        form = {"name": "", "host": "", "port": "22", "username": ""}
        errors = []
        if request.method == "POST":
            if not _csrf_ok():
                errors.append("The form expired. Submit it again.")
            form["name"] = request.form.get("name", "").strip()
            form["host"] = request.form.get("host", "").strip()
            form["port"] = request.form.get("port", "").strip() or "22"
            form["username"] = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not errors:
                port, errors = _validate(form, password)
            else:
                port = None
            if not errors:
                server = app.config["STORE"].add(
                    form["name"], form["host"], port, form["username"], password
                )
                if app.config.get("POLL_ON_ADD"):
                    threading.Thread(
                        target=poll_server,
                        args=(app.config["STORE"], collect, server),
                        name="metric-poll-now",
                        daemon=True,
                    ).start()
                return redirect(url_for("index"))
        return render_template(
            "add_server.html", form=form, errors=errors, csrf_token=_csrf_token()
        ), (400 if errors else 200)

    @app.post("/servers/<server_id>/remove")
    @login_required
    def remove_server(server_id):
        if not ID_RE.fullmatch(server_id):
            abort(404)
        if not _csrf_ok():
            abort(400)
        if not app.config["STORE"].remove(server_id):
            abort(404)
        return redirect(url_for("index"))

    @app.route("/servers/<server_id>")
    @login_required
    def server_detail(server_id):
        if not ID_RE.fullmatch(server_id):
            abort(404)
        detail = app.config["STORE"].detail(server_id)
        if detail is None:
            abort(404)
        detail["chart"] = _chart(detail["samples"])
        return render_template("detail.html", server=detail)

    @app.errorhandler(404)
    def not_found(_error):
        if session.get("user") != "admin":
            return redirect(url_for("login"))
        return render_template("error.html", message="That server is not in the list."), 404

    @app.template_filter("bytes")
    def bytes_filter(value):
        return format_bytes(value)

    @app.template_filter("rate")
    def rate_filter(value):
        if value is None:
            return "Waiting for next sample"
        return format_rate(value)

    @app.template_filter("cpu")
    def cpu_filter(value):
        if value is None:
            return "Waiting for next sample"
        return f"{value:.1f}%"

    @app.template_filter("when")
    def when_filter(value):
        if not value:
            return "—"
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))

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


def _csrf_token():
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def _csrf_ok():
    sent = request.form.get("csrf_token", "")
    expected = session.get("csrf", "")
    if not sent or not expected:
        return False
    return secrets.compare_digest(sent, expected)


def _validate(form, password):
    errors = []
    if not form["name"] or any(ord(char) < 32 for char in form["name"]) or len(form["name"]) > 80:
        errors.append("Display name is required.")
    if not HOST_RE.fullmatch(form["host"]):
        errors.append("Host must be a hostname or IP address.")
    if not USER_RE.fullmatch(form["username"]):
        errors.append("SSH username is required.")
    if not isinstance(password, str) or not password or "\x00" in password or len(password) > 256:
        errors.append("SSH password is required.")
    try:
        port = int(form["port"])
    except (TypeError, ValueError):
        errors.append("SSH port must be a number from 1 to 65535.")
        port = None
    else:
        if port < 1 or port > 65535:
            errors.append("SSH port must be a number from 1 to 65535.")
            port = None
    return port, errors


def _chart(samples):
    labels, cpu, memory, net_in, net_out = [], [], [], [], []
    for sample in samples:
        labels.append(time.strftime("%H:%M:%S", time.localtime(sample["ts"])))
        cpu.append(sample["cpu_percent"])
        memory.append(sample["memory"]["used_percent"])
        net_in.append(sample["net_in_bps"])
        net_out.append(sample["net_out_bps"])
    return {
        "labels": labels,
        "cpu": cpu,
        "memory": memory,
        "net_in": net_in,
        "net_out": net_out,
    }


def format_bytes(value):
    if value is None:
        return "—"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            if unit == "B":
                return f"{amount:.0f} B"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} TB"


def format_rate(value):
    amount = float(value)
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if amount < 1024 or unit == "GB/s":
            if unit == "B/s":
                return f"{amount:.0f} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB/s"


def _empty_store_path():
    return Path(tempfile.mkdtemp(prefix="monitor-")) / "servers.json"


def start_poller(store):
    thread = threading.Thread(
        target=poll_loop,
        args=(store, collect),
        name="metric-poller",
        daemon=True,
    )
    thread.start()
    return thread


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    load_dotenv(ROOT / ".env")
    secret, password_hash = require_settings(os.environ)
    store = Store(demo_server_path(ROOT))
    app = create_app(secret, password_hash, store=store)
    app.config["POLL_ON_ADD"] = True
    start_poller(store)
    app.run(host="127.0.0.1", port=5000, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
