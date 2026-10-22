"""Participant profile, team, project submission and protected poster delivery."""
import io
import secrets
import warnings
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm.attributes import set_committed_value

from .auth import login_required
from .extensions import db
from .models import AuditLog, Category, Project, User

bp = Blueprint("participant", __name__)


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/dashboard")
@login_required
def dashboard():
    if g.user.role == "admin":
        return redirect(url_for("admin.dashboard"))
    from .passes import pass_eligibility
    eligible, reason = pass_eligibility(g.user)
    team = g.user.team
    project = team.project if team else None
    return render_template("dashboard.html", team=team, project=project, eligible=eligible, eligibility_reason=reason, checkin=g.user.checkin)


def exhibitor_team(lock=False):
    if g.user.role != "exhibitor" or not g.user.team:
        abort(403)
    if lock:
        # Keep the same lock order as approval/check-in: person, then project.
        # Re-read under the lock so a concurrent approval cannot be overwritten.
        g.user = db.session.scalar(db.select(User).where(User.id == g.user.id).with_for_update().execution_options(populate_existing=True))
        locked_project = db.session.scalar(db.select(Project).where(Project.team_id == g.user.team.id).with_for_update().execution_options(populate_existing=True))
        # A current locking read may see a first submission that is absent from
        # an older MySQL repeatable-read snapshot. Use that result directly.
        set_committed_value(g.user.team, "project", locked_project)
    return g.user.team


@bp.route("/team", methods=["GET", "POST"])
@login_required
def team():
    team = exhibitor_team(lock=request.method == "POST")
    project = team.project
    if request.method == "POST":
        if project and project.status == "approved":
            flash("Your approved team is locked. Ask the organizer to reopen the application before changing it.", "error")
            return redirect(url_for("participant.team"))
        name = request.form.get("name", "").strip()
        institution = request.form.get("institution", "").strip()
        members = request.form.get("members", "").strip()
        if not 2 <= len(name) <= 120 or not 2 <= len(institution) <= 180:
            flash("Enter a team name and institution between 2 and 120 / 180 characters.", "error")
            return render_template("team.html", team=team, project=project), 400
        if len(members) > 2000 or len(members.splitlines()) > 10:
            flash("List up to 10 team members, one per line (2,000 characters maximum).", "error")
            return render_template("team.html", team=team, project=project), 400
        team.name, team.institution, team.members = name, institution, members
        db.session.add(AuditLog(user_id=g.user.id, action="team_updated", details=f"Team {team.id}: {name}"))
        db.session.commit()
        flash("Your team profile has been saved.", "success")
        return redirect(url_for("participant.team"))
    return render_template("team.html", team=team, project=project)


def store_poster(upload):
    """Decode and re-encode the image; never store client filenames or executable bytes."""
    try:
        data = upload.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("Poster must be under 8 MB.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise ValueError("Upload a PNG or JPEG poster.")
                if image.width * image.height > 24_000_000:
                    raise ValueError("Poster resolution must be under 24 megapixels.")
                image.load()
                filename = f"{secrets.token_hex(20)}.png"
                destination = Path(current_app.config["UPLOAD_FOLDER"]) / filename
                image.convert("RGB").save(destination, "PNG", optimize=True)
        return filename
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise ValueError("This is not a valid PNG or JPEG image.") from error


@bp.route("/project", methods=["GET", "POST"])
@login_required
def project():
    team = exhibitor_team(lock=request.method == "POST")
    project = team.project
    if request.method == "POST":
        if project and project.status == "approved":
            flash("Your approved project is locked. Ask the organizer to reopen it before making changes.", "error")
            return redirect(url_for("participant.project"))
        title = request.form.get("title", "").strip()
        abstract = request.form.get("abstract", "").strip()
        requirements = request.form.get("requirements", "").strip()
        category_id = request.form.get("category_id", type=int)
        category = db.session.get(Category, category_id) if category_id else None
        error = None
        if not 5 <= len(title) <= 180:
            error = "Enter a project title between 5 and 180 characters."
        elif not 50 <= len(abstract) <= 10000:
            error = "Enter an abstract between 50 and 10,000 characters."
        elif not category:
            error = "Choose an available project category."
        elif len(requirements) > 2000:
            error = "Booth requirements must be 2,000 characters or fewer."
        elif not team.institution:
            error = "Complete your team institution before submitting your project."
        new_filename = None
        poster = request.files.get("poster")
        if not error and poster and poster.filename:
            try:
                new_filename = store_poster(poster)
            except ValueError as upload_error:
                error = str(upload_error)
        if error:
            flash(error, "error")
            return render_template("project.html", project=project, team=team), 400
        old_filename = project.poster_filename if project else None
        if not project:
            project = Project(team=team)
            db.session.add(project)
        project.title = title
        project.abstract = abstract
        project.category_id = category.id
        project.requirements = requirements
        project.status = "pending"
        project.review_comment = ""
        project.reviewed_at = None
        if project.booth:
            project.booth.project_id = None
        if new_filename:
            project.poster_filename = new_filename
        g.user.token_version += 1
        db.session.add(AuditLog(user_id=g.user.id, action="project_submitted", details=title))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if new_filename:
                (Path(current_app.config["UPLOAD_FOLDER"]) / new_filename).unlink(missing_ok=True)
            raise
        if new_filename and old_filename:
            (Path(current_app.config["UPLOAD_FOLDER"]) / old_filename).unlink(missing_ok=True)
        flash("Project submitted. The organizing committee will review your application.", "success")
        return redirect(url_for("participant.dashboard"))
    return render_template("project.html", project=project, team=team)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        organization = request.form.get("organization", "").strip()
        phone = request.form.get("phone", "").strip()
        if not 2 <= len(name) <= 120 or len(organization) > 180 or len(phone) > 40:
            flash("Check your name (2–120 characters), organization (up to 180) and phone (up to 40).", "error")
            return render_template("profile.html"), 400
        g.user.name, g.user.organization, g.user.phone = name, organization, phone
        db.session.commit()
        flash("Your profile has been updated.", "success")
        return redirect(url_for("participant.profile"))
    return render_template("profile.html")


@bp.get("/posters/<int:project_id>")
@login_required
def poster(project_id):
    project = db.get_or_404(Project, project_id)
    if g.user.role != "admin" and project.team.user_id != g.user.id:
        abort(403)
    if not project.poster_filename:
        abort(404)
    response = send_from_directory(current_app.config["UPLOAD_FOLDER"], project.poster_filename)
    response.headers["Cache-Control"] = "no-store"
    return response
