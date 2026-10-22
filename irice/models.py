"""Single-event models. Attendance always counts registered accounts, not team members."""
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(254), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="exhibitor")
    organization = db.Column(db.String(180), nullable=False, default="")
    phone = db.Column(db.String(40), nullable=False, default="")
    approval_status = db.Column(db.String(20), nullable=False, default="pending")
    review_comment = db.Column(db.Text, nullable=False, default="")
    token_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    team = db.relationship("Team", back_populates="user", uselist=False, cascade="all, delete-orphan")
    checkin = db.relationship("CheckIn", foreign_keys="CheckIn.user_id", back_populates="user", uselist=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Team(db.Model):
    __tablename__ = "teams"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    institution = db.Column(db.String(180), nullable=False, default="")
    members = db.Column(db.Text, nullable=False, default="")
    user = db.relationship("User", back_populates="team")
    project = db.relationship("Project", back_populates="team", uselist=False, cascade="all, delete-orphan")


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.String(240), nullable=False, default="")
    color = db.Column(db.String(7), nullable=False, default="#167d75")


class Project(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    abstract = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, nullable=False, default="")
    poster_filename = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    review_comment = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    team = db.relationship("Team", back_populates="project")
    category = db.relationship("Category")
    booth = db.relationship("Booth", back_populates="project", uselist=False)


class Booth(db.Model):
    __tablename__ = "booths"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(24), nullable=False, unique=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    location = db.Column(db.String(120), nullable=False, default="Exhibition hall")
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, unique=True)
    project = db.relationship("Project", back_populates="booth")
    category = db.relationship("Category")


class CheckIn(db.Model):
    __tablename__ = "check_ins"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True)
    scanner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    user = db.relationship("User", foreign_keys=[user_id], back_populates="checkin")
    scanner = db.relationship("User", foreign_keys=[scanner_id])


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    details = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    user = db.relationship("User")
