"""Repeatable initialization and explicit organizer provisioning."""
import re
import secrets

import click
from flask.cli import with_appcontext

from .extensions import db
from .models import Booth, Category, Project, Team, User

DEFAULT_CATEGORIES = [
    ("Engineering & Technology", "Practical engineering and connected systems.", "#167d75"),
    ("Computing & AI", "Software, data science and artificial intelligence.", "#5366b0"),
    ("Sustainability", "Ideas for a healthier, more sustainable future.", "#60945a"),
    ("Creative Innovation", "Design, learning and interdisciplinary innovation.", "#bc8148"),
]


def seed_defaults():
    for name, description, color in DEFAULT_CATEGORIES:
        if not db.session.scalar(db.select(Category).where(Category.name == name)):
            db.session.add(Category(name=name, description=description, color=color))
    db.session.flush()
    for index in range(1, 21):
        code = f"A-{index:02d}"
        if not db.session.scalar(db.select(Booth).where(Booth.code == code)):
            db.session.add(Booth(code=code, location="Main exhibition hall"))
    db.session.commit()


@click.command("init-db")
@with_appcontext
def init_db():
    """Create missing tables and default categories/20 booths. Does not erase data."""
    db.create_all()
    seed_defaults()
    click.echo("Database initialized. Default categories and 20 booths are available.")


@click.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--name", prompt=True, default="Event organizer")
@click.password_option(confirmation_prompt=True)
@with_appcontext
def create_admin(email, name, password):
    """Create an organizer through a trusted terminal; password is never echoed."""
    email = email.strip().lower()
    name = name.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
        raise click.ClickException("Enter a valid email address.")
    if not 2 <= len(name) <= 120 or not 10 <= len(password) <= 128:
        raise click.ClickException("Use a name of 2–120 characters and a password of 10–128 characters.")
    if db.session.scalar(db.select(User).where(User.email == email)):
        raise click.ClickException("That account already exists. No roles or passwords were changed.")
    user = User(name=name, email=email, role="admin", approval_status="approved")
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo("Organizer created. Sign in using the credentials you just chose.")


@click.command("seed-demo")
@with_appcontext
def seed_demo():
    """Add clearly identified fictional sample applications; creates no known passwords."""
    db.create_all()
    seed_defaults()
    examples = [
        ("AquaSense", "AquaSense: smarter water for every community", "Engineering & Technology", "approved"),
        ("Neural Nexus", "An accessible learning companion powered by AI", "Computing & AI", "pending"),
        ("Green Circuit", "Turning food waste into a circular opportunity", "Sustainability", "pending"),
        ("Studio Bloom", "Tactile storytelling for inclusive classrooms", "Creative Innovation", "approved"),
        ("Urban Pulse", "Low-cost sensing for more liveable cities", "Engineering & Technology", "rejected"),
    ]
    added = 0
    for index, (team_name, title, category_name, status) in enumerate(examples, 1):
        email = f"demo.exhibitor{index}@example.test"
        if db.session.scalar(db.select(User).where(User.email == email)):
            continue
        user = User(name=f"Sample Exhibitor {index}", email=email, role="exhibitor", organization="Southern University College")
        user.set_password(secrets.token_urlsafe(32))
        team = Team(user=user, name=f"{team_name} [DEMO]", institution="Southern University College", members="Fictional sample data")
        category = db.session.scalar(db.select(Category).where(Category.name == category_name))
        project = Project(team=team, category=category, title=title, abstract=f"Fictional demonstration project. {title}. This entry illustrates the I-RICE review and exhibition workflow and is not a real submission.", status=status, requirements="One table and a power outlet.", review_comment="Please provide more detail on the evaluation method." if status == "rejected" else "")
        db.session.add(project)
        db.session.flush()
        if status == "approved":
            booth = db.session.scalar(db.select(Booth).where(Booth.project_id.is_(None)).order_by(Booth.code))
            if booth:
                booth.project = project
        added += 1
    db.session.commit()
    click.echo(f"Added {added} fictional demo projects. Sample accounts have random, undisclosed passwords.")


def init_app(app):
    app.cli.add_command(init_db)
    app.cli.add_command(create_admin)
    app.cli.add_command(seed_demo)
