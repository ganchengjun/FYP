"""Organizer workflows: review, allocation, attendance and reporting."""

import csv
import io
import re

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError

from .auth import admin_required
from .extensions import db
from .models import AuditLog, Booth, Category, CheckIn, Project, Team, User, utcnow

bp = Blueprint("admin", __name__, url_prefix="/admin")
_STATUSES = {"pending", "approved", "rejected"}


def _audit(action, details):
    db.session.add(AuditLog(user_id=g.user.id, action=action, details=details))


def _count(model, *criteria):
    return db.session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0


def dashboard_metrics():
    """Counts represent projects, booths and individual registered pass holders."""
    total_people = _count(User, User.role != "admin")
    approved_exhibitors = db.session.scalar(
        select(func.count()).select_from(User).join(Team, Team.user_id == User.id)
        .join(Project, Project.team_id == Team.id)
        .where(User.role == "exhibitor", Project.status == "approved")
    ) or 0
    approved_visitors = _count(
        User, User.role.in_(["attendee", "evaluator"]), User.approval_status == "approved"
    )
    checked_in = _count(CheckIn)
    return {
        "total_projects": _count(Project),
        "pending_projects": _count(Project, Project.status == "pending"),
        "approved_projects": _count(Project, Project.status == "approved"),
        "rejected_projects": _count(Project, Project.status == "rejected"),
        "total_booths": _count(Booth),
        "allocated_booths": _count(Booth, Booth.project_id.is_not(None)),
        "total_people": total_people,
        "approved_people": approved_exhibitors + approved_visitors,
        "checked_in": checked_in,
        "checkin_rate": round(100 * checked_in / total_people, 1) if total_people else 0,
    }


@bp.get("/")
@admin_required
def dashboard():
    category_rows = db.session.execute(
        select(Category.name, Category.color, func.count(Project.id).label("count"))
        .outerjoin(Project, Project.category_id == Category.id)
        .group_by(Category.id, Category.name, Category.color).order_by(Category.name)
    ).all()
    return render_template(
        "admin/dashboard.html",
        metrics=dashboard_metrics(),
        recent_projects=db.session.scalars(select(Project).order_by(Project.created_at.desc(), Project.id.desc()).limit(6)).all(),
        recent_checkins=db.session.scalars(select(CheckIn).order_by(CheckIn.created_at.desc(), CheckIn.id.desc()).limit(6)).all(),
        category_stats=[{"name": row.name, "color": row.color, "count": row._mapping["count"]} for row in category_rows],
    )


@bp.get("/applications")
@admin_required
def applications():
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()[:200]
    category_id = request.args.get("category_id", type=int)
    if category_id is not None and not 1 <= category_id <= 2_147_483_647:
        category_id = None
    query = select(Project).join(Team)
    if status in _STATUSES:
        query = query.where(Project.status == status)
    if q:
        query = query.where(or_(Project.title.ilike(f"%{q}%"), Team.name.ilike(f"%{q}%")))
    if category_id:
        query = query.where(Project.category_id == category_id)
    projects = db.session.scalars(query.order_by(Project.created_at.desc(), Project.id.desc())).all()
    return render_template("admin/applications.html", projects=projects, q=q, status=status, category_id=category_id)


@bp.get("/applications/<int:project_id>")
@admin_required
def application(project_id):
    if not 1 <= project_id <= 2_147_483_647:
        abort(404)
    project = db.get_or_404(Project, project_id)
    available_booths = db.session.scalars(
        select(Booth).where(
            or_(Booth.project_id.is_(None), Booth.project_id == project.id),
            or_(Booth.category_id.is_(None), Booth.category_id == project.category_id),
        ).order_by(Booth.code)
    ).all()
    return render_template("admin/application.html", project=project, available_booths=available_booths)


@bp.post("/applications/<int:project_id>/review")
@admin_required
def review(project_id):
    if not 1 <= project_id <= 2_147_483_647:
        abort(404)
    status = request.form.get("status", "").strip()
    comment = request.form.get("comment", "").strip()
    if status not in _STATUSES or len(comment) > 2000:
        flash("Choose a valid review decision and keep comments within 2,000 characters.", "danger")
        return redirect(url_for("admin.application", project_id=project_id))
    if status == "rejected" and not comment:
        flash("Add a comment so the team knows how to improve its submission.", "danger")
        return redirect(url_for("admin.application", project_id=project_id))
    owner_id = db.session.scalar(select(Team.user_id).join(Project, Project.team_id == Team.id).where(Project.id == project_id))
    if owner_id is None:
        abort(404)
    # Check-in locks the pass holder before examining project approval. Use the
    # same lock order so scans and revocations serialize without deadlocking.
    user = db.session.scalar(select(User).where(User.id == owner_id).with_for_update().execution_options(populate_existing=True))
    project = db.session.scalar(select(Project).where(Project.id == project_id).with_for_update().execution_options(populate_existing=True))
    if project is None:
        abort(404)
    previous = project.status
    if previous == "approved" and status != "approved":
        # Revocation takes effect for already-issued QR codes immediately.
        user.token_version += 1
        old_booth = db.session.scalar(select(Booth).where(Booth.project_id == project.id).with_for_update())
        if old_booth:
            old_booth.project_id = None
    project.status = status
    project.review_comment = comment
    project.reviewed_at = utcnow()
    _audit("project.review", f"Project #{project.id}: {previous} → {status}.")
    db.session.commit()
    flash(f"Application marked {status}.", "success")
    return redirect(url_for("admin.application", project_id=project_id))


@bp.post("/applications/<int:project_id>/booth")
@admin_required
def allocate(project_id):
    if not 1 <= project_id <= 2_147_483_647:
        abort(404)
    raw_booth = request.form.get("booth_id", "").strip()
    try:
        if len(raw_booth) > 10:
            raise ValueError("Booth id out of range")
        booth_id = int(raw_booth) if raw_booth else None
    except ValueError:
        flash("Choose a valid exhibition booth.", "danger")
        return redirect(url_for("admin.application", project_id=project_id))
    if booth_id is not None and not 1 <= booth_id <= 2_147_483_647:
        flash("Choose a valid exhibition booth.", "danger")
        return redirect(url_for("admin.application", project_id=project_id))
    try:
        # Serialize reviews and allocations of the same application. Lock both
        # involved booth rows in a stable order for cross-project reassignments.
        project = db.session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if project is None:
            abort(404)
        if project.status != "approved":
            flash("Approve the application before assigning an exhibition booth.", "warning")
            return redirect(url_for("admin.application", project_id=project_id))
        rows = db.session.scalars(
            select(Booth).where(or_(Booth.project_id == project.id, Booth.id == booth_id))
            .order_by(Booth.id).with_for_update().execution_options(populate_existing=True)
        ).all()
        old_booth = next((booth for booth in rows if booth.project_id == project.id), None)
        target = next((booth for booth in rows if booth.id == booth_id), None)
        if booth_id is not None and target is None:
            flash("That booth no longer exists. Choose another booth.", "danger")
            return redirect(url_for("admin.application", project_id=project_id))
        if target and target.project_id not in (None, project.id):
            flash("That booth has already been allocated. Choose an available booth.", "warning")
            return redirect(url_for("admin.application", project_id=project_id))
        if target and target.category_id is not None and target.category_id != project.category_id:
            flash("Choose a booth assigned to this project's category or a general booth.", "warning")
            return redirect(url_for("admin.application", project_id=project_id))
        previous = old_booth.code if old_booth else "unassigned"
        if old_booth and old_booth is not target:
            old_booth.project_id = None
            db.session.flush()
        if target:
            target.project_id = project.id
        _audit("booth.allocate", f"Project #{project.id}: {previous} → {target.code if target else 'unassigned'}.")
        db.session.commit()
        flash("Booth allocation updated.", "success")
    except (IntegrityError, OperationalError):
        db.session.rollback()
        flash("The allocation changed while you were working. Refresh and choose an available booth.", "warning")
    return redirect(url_for("admin.application", project_id=project_id))


@bp.route("/booths", methods=["GET", "POST"])
@admin_required
def booths():
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        location = request.form.get("location", "").strip()
        category_raw = request.form.get("category_id", "").strip()
        category_id = int(category_raw) if category_raw.isascii() and category_raw.isdigit() and len(category_raw) <= 10 else None
        category = db.session.get(Category, category_id) if category_id and 1 <= category_id <= 2_147_483_647 else None
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,19}", code) or len(location) > 120:
            flash("Use a booth code of up to 20 letters, digits, dots or hyphens and a location of up to 120 characters.", "danger")
        elif category_raw and category is None:
            flash("Choose an existing category or leave the booth open to all categories.", "danger")
        else:
            db.session.add(Booth(code=code, location=location, category_id=category.id if category else None))
            _audit("booth.create", f"Created booth {code}.")
            try:
                db.session.commit()
                flash(f"Booth {code} added.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("That booth code already exists.", "danger")
        return redirect(url_for("admin.booths"))
    all_booths = db.session.scalars(select(Booth).order_by(Booth.code)).all()
    return render_template("admin/booths.html", booths=all_booths)


@bp.post("/categories")
@admin_required
def categories():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    color = request.form.get("color", "#147d78").strip()
    if not 2 <= len(name) <= 80 or len(description) > 240 or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        flash("Enter a category name (2–80 characters), description (up to 240), and a valid hex color.", "danger")
        return redirect(url_for("admin.booths"))
    db.session.add(Category(name=name, description=description, color=color))
    _audit("category.create", f"Created category {name}.")
    try:
        db.session.commit()
        flash("Category added.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("That category name already exists.", "danger")
    return redirect(url_for("admin.booths"))


@bp.get("/attendees")
@admin_required
def attendees():
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()[:200]
    query = select(User).where(User.role != "admin")
    if q:
        query = query.where(or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%"), User.organization.ilike(f"%{q}%")))
    if status in _STATUSES:
        # Exhibitor admission follows the project's review, not the otherwise
        # unused User.approval_status column.
        query = query.outerjoin(Team, Team.user_id == User.id).outerjoin(Project, Project.team_id == Team.id).where(
            or_(
                (User.role.in_(["attendee", "evaluator"])) & (User.approval_status == status),
                (User.role == "exhibitor") & (Project.status == status),
                (User.role == "exhibitor") & Project.id.is_(None) if status == "pending" else False,
            )
        )
    people = db.session.scalars(query.order_by(User.created_at.desc(), User.id.desc())).all()
    return render_template("admin/attendees.html", people=people, q=q, status=status)


@bp.post("/attendees/<int:user_id>/review")
@admin_required
def review_attendee(user_id):
    if not 1 <= user_id <= 2_147_483_647:
        abort(404)
    status = request.form.get("status", "").strip()
    comment = request.form.get("comment", "").strip()
    user = db.session.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if user is None:
        abort(404)
    if user.role not in {"attendee", "evaluator"}:
        abort(400, description="Exhibitor admission is managed through the project application.")
    if status not in _STATUSES or len(comment) > 2000 or (status == "rejected" and not comment):
        flash("Choose a valid decision and include a comment when rejecting a registration.", "danger")
        return redirect(url_for("admin.attendees"))
    previous = user.approval_status
    if previous == "approved" and status != "approved":
        user.token_version += 1
    user.approval_status = status
    user.review_comment = comment
    _audit("registration.review", f"Registration #{user.id}: {previous} → {status}.")
    db.session.commit()
    flash(f"Registration marked {status}.", "success")
    return redirect(url_for("admin.attendees"))


def _csv_safe(value):
    text = "" if value is None else str(value)
    # Spreadsheet programs can treat formulas preceded by whitespace/control
    # characters as executable cells. Always force potentially active cells
    # to plain text; CSV quoting alone does not stop formula execution.
    return "'" + text if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


@bp.get("/report.csv")
@admin_required
def report():
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Name", "Email", "Registration type", "Organization", "Approval", "Team", "Project", "Category", "Booth", "Checked in (UTC)"])
    for user in db.session.scalars(select(User).where(User.role != "admin").order_by(User.id)):
        project = user.team.project if user.team else None
        row = [user.name, user.email, user.role, user.organization,
               project.status if project else ("not submitted" if user.role == "exhibitor" else user.approval_status),
               user.team.name if user.team else "", project.title if project else "",
               project.category.name if project and project.category else "",
               project.booth.code if project and project.booth else "",
               user.checkin.created_at.isoformat(timespec="seconds") if user.checkin else ""]
        writer.writerow([_csv_safe(value) for value in row])
    response = Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = "attachment; filename=irice-registration-report.csv"
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/activity")
@admin_required
def audit():
    logs = db.session.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(200)).all()
    return render_template("admin/activity.html", logs=logs)
