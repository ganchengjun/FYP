"""Signed admission passes, printable documents, and organizer check-in."""

import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import qrcode
from flask import Blueprint, current_app, g, jsonify, render_template, request, send_file
from itsdangerous import BadData, SignatureExpired, URLSafeTimedSerializer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .auth import admin_required, login_required
from .extensions import db
from .models import AuditLog, CheckIn, Project, Team, User


bp = Blueprint("passes", __name__, url_prefix="/passes")
TOKEN_LIFETIMES = {"live": 180, "download": 24 * 60 * 60}
LOCAL_TIMEZONE = ZoneInfo("Asia/Kuala_Lumpur")
# The event accepts Chinese names as well as Latin text. ReportLab's default
# Helvetica renders CJK names as missing glyphs; its standard CID font preserves
# that text without fetching fonts or relying on host-specific font paths.
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
pdfmetrics.registerFontFamily(
    "STSong-Light", normal="STSong-Light", bold="STSong-Light",
    italic="STSong-Light", boldItalic="STSong-Light",
)


def pass_eligibility(user):
    """Check the current database state, including changes since QR issuance."""
    if user.role == "exhibitor":
        project = user.team.project if user.team else None
        if project is None:
            return False, "Submit a project application before requesting an admission pass."
        if project.status != "approved":
            return False, "Your project must be approved before an admission pass is available."
        return True, "Your project has been approved."
    if user.role in {"attendee", "evaluator"}:
        if user.approval_status != "approved":
            return False, "An organizer must approve your registration before admission."
        return True, "Your registration has been approved."
    return False, "Organizer accounts do not have participant admission passes."


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="irice-admission-v1")


def issue_token(user, kind="live"):
    """Issue a signed token; callers must first check admission eligibility."""
    if kind not in TOKEN_LIFETIMES:
        raise ValueError("Unknown admission token kind")
    return _serializer().dumps({"uid": user.id, "v": user.token_version, "kind": kind})


def _qr_png(token):
    image = qrcode.make(token)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _qr_data(token):
    return "data:image/png;base64," + base64.b64encode(_qr_png(token)).decode("ascii")


def _no_store(response):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return response


def _error(message, status=400):
    return _no_store(jsonify(ok=False, message=message)), status


def _project(user):
    return user.team.project if user.role == "exhibitor" and user.team else None


@bp.get("/")
@login_required
def view():
    eligible, reason = pass_eligibility(g.user)
    token = issue_token(g.user) if eligible else None
    response = current_app.make_response(
        render_template(
            "pass.html", user=g.user, project=_project(g.user), eligible=eligible,
            reason=reason, token=token, qr_data=_qr_data(token) if token else None,
            checkin=g.user.checkin,
        )
    )
    return _no_store(response)


@bp.get("/token")
@login_required
def token():
    eligible, reason = pass_eligibility(g.user)
    if not eligible:
        return _error(reason, 403)
    value = issue_token(g.user)
    expiry = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_LIFETIMES["live"])
    return _no_store(jsonify(
        ok=True, token=value, qr_data=_qr_data(value),
        expires_in=TOKEN_LIFETIMES["live"], expires_at=expiry.isoformat(),
    ))


def _document(filename, heading, rows, qr_token=None):
    """Render user content as escaped reportlab text, never as markup."""
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=24 * mm, leftMargin=24 * mm,
        topMargin=22 * mm, bottomMargin=22 * mm,
        title=heading, author="I-RICE Exhibition Management",
    )
    styles = getSampleStyleSheet()
    for name in ("Title", "Heading1", "BodyText"):
        styles[name].fontName = "STSong-Light"
    styles["Title"].textColor = colors.HexColor("#123c4a")
    styles["BodyText"].spaceAfter = 9
    content = [Paragraph("I-RICE", styles["Title"]), Paragraph(heading, styles["Heading1"]), Spacer(1, 8 * mm)]
    for label, value in rows:
        text = f"<b>{escape(str(label))}:</b> {escape(str(value))}"
        content.append(Paragraph(text, styles["BodyText"]))
    if qr_token:
        content.extend([Spacer(1, 8 * mm), Image(BytesIO(_qr_png(qr_token)), width=65 * mm, height=65 * mm)])
    document.build(content)
    output.seek(0)
    return _no_store(send_file(output, mimetype="application/pdf", as_attachment=True, download_name=filename))


@bp.get("/download")
@login_required
def download():
    eligible, reason = pass_eligibility(g.user)
    if not eligible:
        return _error(reason, 403)
    project = _project(g.user)
    expires = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_LIFETIMES["download"])
    rows = [("Name", g.user.name), ("Admission type", g.user.role.title())]
    if project:
        rows.extend([("Project", project.title), ("Team", g.user.team.name),
                     ("Booth", project.booth.code if project.booth else "Awaiting allocation")])
    rows.extend([
        ("QR expires", expires.astimezone(LOCAL_TIMEZONE).strftime("%d %b %Y, %H:%M:%S MYT (UTC+08:00)")),
        ("Validity", "This downloaded QR is valid for 24 hours. Approval must remain active. Obtain a new pass after expiry."),
        ("Live pass", "Your online admission QR refreshes automatically before its 180-second expiry. Revoked approval invalidates both versions immediately."),
        ("Admission scope", "This pass admits the named registered account only. Informational team members need their own approved registration."),
    ])
    return _document("irice-admission-pass.pdf", "Admission pass", rows, issue_token(g.user, "download"))


@bp.get("/certificate")
@login_required
def certificate():
    eligible, reason = pass_eligibility(g.user)
    project = _project(g.user)
    if not eligible:
        return _error(reason, 403)
    if project is None or project.booth is None:
        return _error("A booth certificate is available after an approved project receives a booth.", 403)
    return _document("irice-booth-certificate.pdf", "Booth allocation certificate", [
        ("Project", project.title), ("Category", project.category.name),
        ("Team", g.user.team.name), ("Registered exhibitor", g.user.name),
        ("Booth", project.booth.code), ("Location", project.booth.location or "See organizer for details"),
        ("Issued", datetime.now(LOCAL_TIMEZONE).strftime("%d %b %Y, %H:%M MYT")),
        ("Purpose", "This document confirms the current booth allocation; it is not an admission pass."),
    ])


@bp.get("/scanner")
@admin_required
def scanner():
    return render_template("admin/scanner.html")


def _extract_token(value):
    if not isinstance(value, str):
        raise ValueError("Scan an admission QR code or enter its token.")
    value = value.strip()
    if not value or len(value) > 4096:
        raise ValueError("The admission token is missing or too long.")
    # Supported QR URLs are data only. Never fetch the supplied URL.
    if value.startswith(("https://", "http://")):
        values = parse_qs(urlsplit(value).query, max_num_fields=20).get("token", [])
        if len(values) != 1 or not values[0]:
            raise ValueError("The QR URL must contain one admission token.")
        value = values[0]
    return value


def _validate_token(value):
    serializer = _serializer()
    payload = serializer.loads(value, max_age=TOKEN_LIFETIMES["download"])
    if not isinstance(payload, dict):
        raise ValueError("Invalid admission pass.")
    if type(payload.get("uid")) is not int or payload["uid"] < 1:
        raise ValueError("Invalid admission pass.")
    if type(payload.get("v")) is not int or payload["v"] < 1:
        raise ValueError("Invalid admission pass.")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in TOKEN_LIFETIMES:
        raise ValueError("Invalid admission pass.")
    # Recheck the signed timestamp against the authenticated token kind's limit.
    serializer.loads(value, max_age=TOKEN_LIFETIMES[kind])
    user = db.session.scalar(
        select(User).where(User.id == payload["uid"]).with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise ValueError("This admission registration no longer exists.")
    if payload["v"] != user.token_version:
        raise ValueError("This admission pass has been revoked. Ask the participant to refresh it.")
    if user.role == "exhibitor":
        # A locking read observes the latest approval even under MySQL's default
        # repeatable-read isolation rather than an earlier request snapshot.
        project = db.session.scalar(
            select(Project).join(Team).where(Team.user_id == user.id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if project is None or project.status != "approved":
            raise ValueError("The exhibitor's project is not currently approved.")
    eligible, reason = pass_eligibility(user)
    if not eligible:
        raise ValueError(reason)
    return user


def _checkin_result(record, user, duplicate):
    timestamp = record.created_at.replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE).isoformat()
    return _no_store(jsonify(
        ok=True, duplicate=duplicate, name=user.name, role=user.role, time=timestamp,
        message="Already checked in. No additional attendance was recorded." if duplicate else "Check-in recorded successfully.",
    ))


@bp.post("/check-in")
@admin_required
def checkin():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Send a JSON object containing an admission token.")
    try:
        value = _extract_token(data.get("token"))
        user = _validate_token(value)
    except SignatureExpired:
        return _error("This QR code has expired. Ask the participant to refresh their pass.")
    except BadData:
        return _error("The QR code is invalid or has been altered.")
    except ValueError as exc:
        return _error(str(exc))
    except TypeError:
        return _error("Invalid admission pass.")

    existing = db.session.scalar(select(CheckIn).where(CheckIn.user_id == user.id))
    if existing:
        return _checkin_result(existing, user, True)
    admission_user_id = user.id
    record = CheckIn(user_id=admission_user_id, scanner_id=g.user.id)
    db.session.add(record)
    db.session.add(AuditLog(user_id=g.user.id, action="check_in", details=f"Recorded admission for user #{admission_user_id}."))
    try:
        db.session.commit()
    except IntegrityError:
        # A second organizer can win the race after our initial lookup. The
        # database uniqueness constraint is the source of truth for attendance.
        db.session.rollback()
        existing = db.session.scalar(select(CheckIn).where(CheckIn.user_id == admission_user_id))
        if existing is None:
            return _error("Check-in could not be recorded. Please try again.", 409)
        return _checkin_result(existing, db.session.get(User, admission_user_id), True)
    return _checkin_result(record, user, False)
