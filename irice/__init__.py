"""Flask application factory for the I-RICE exhibition management system."""
import os
import secrets
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .extensions import csrf, db


@event.listens_for(Engine, "connect")
def _sqlite_foreign_keys(connection, _record):
    if connection.__class__.__module__.startswith("sqlite3"):
        connection.execute("PRAGMA foreign_keys=ON")


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    instance = Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)
    load_dotenv(instance / ".env", override=False)
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        keyfile = instance / "secret.key"
        candidate = instance / f".secret-{secrets.token_hex(12)}.tmp"
        try:
            # Link a completely written file atomically. Racing workers cannot
            # overwrite the shared key or read it while it is still empty.
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(secrets.token_hex(32))
                file.flush()
                os.fsync(file.fileno())
            try:
                os.link(candidate, keyfile)
            except FileExistsError:
                pass
        finally:
            candidate.unlink(missing_ok=True)
        secret = keyfile.read_text(encoding="utf-8").strip()
    if len(secret) < 32 or secret.startswith("REPLACE_WITH"):
        raise RuntimeError("Configure a random SECRET_KEY of at least 32 characters.")
    app.config.from_mapping(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///irice.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        UPLOAD_FOLDER=str(instance / "posters"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        WTF_CSRF_TIME_LIMIT=8 * 60 * 60,
        EVENT_NAME="I-RICE 2026",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    csrf.init_app(app)

    from . import admin, auth, cli, participant, passes

    app.register_blueprint(auth.bp)
    app.register_blueprint(participant.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(passes.bp)
    cli.init_app(app)

    @app.context_processor
    def shared_context():
        from .models import Category
        return {"current_user": getattr(g, "user", None), "categories": db.session.scalars(db.select(Category).order_by(Category.name)).all()}

    @app.template_filter("datetime")
    def format_datetime(value, fmt="%d %b %Y, %I:%M %p"):
        if not value:
            return "—"
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).strftime(fmt)

    @app.template_filter("initials")
    def initials(value):
        return "".join(part[0] for part in str(value or "?").split()[:2]).upper()

    @app.get("/health")
    def health():
        from sqlalchemy import text
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok", database="connected")
        except Exception:
            db.session.rollback()
            return jsonify(status="error", database="unavailable"), 503

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if getattr(g, "user", None) or request.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(CSRFError)
    def csrf_failure(error):
        if request.is_json:
            return jsonify(ok=False, message="Your session expired. Refresh the page and try again."), 400
        return render_template("error.html", code=400, message="Your form session expired. Refresh the page and try again."), 400

    for code, message in [(400, "This request could not be processed."), (403, "You do not have access to this page."), (404, "We could not find this page."), (413, "The file is too large. Upload a PNG or JPEG under 8 MB.")]:
        def handle_error(error, status=code, description=message):
            if request.is_json:
                return jsonify(ok=False, message=description), status
            return render_template("error.html", code=status, message=description), status
        app.register_error_handler(code, handle_error)
    return app
