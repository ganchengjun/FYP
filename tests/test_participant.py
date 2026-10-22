import io

from PIL import Image

from irice.extensions import db
from irice.models import Booth, Category, CheckIn, Project, User


PASSWORD = "Long-test-password-123"


def register(client, email="participant@example.test", role="exhibitor"):
    return client.post("/auth/register", data={"name": "Alex Tan", "email": email, "password": PASSWORD, "role": role, "organization": "Southern University College"})


def submit(client, **extra):
    data = {"title": "Smart water monitoring system", "category_id": "1", "abstract": "A connected water monitoring prototype that detects leaks and tracks consumption with low-cost sensors for local communities.", "requirements": "One table and a power socket."}
    data.update(extra)
    return client.post("/project", data=data)


def png():
    stream = io.BytesIO()
    Image.new("RGB", (100, 100), "teal").save(stream, "PNG")
    stream.seek(0)
    return stream


def test_registration_creates_team_hashes_password_and_submits(app, client):
    assert register(client).status_code == 302
    assert submit(client).status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "participant@example.test"))
        assert user.password_hash != PASSWORD
        assert user.check_password(PASSWORD)
        assert user.team.institution == "Southern University College"
        assert user.team.project.status == "pending"
        assert user.team.project.category_id == 1


def test_public_registration_cannot_create_admin(app, client):
    assert register(client, role="admin").status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(User)) is None


def test_duplicate_email_case_normalization(app, client):
    assert register(client, email="PARTICIPANT@example.test").status_code == 302
    client.post("/auth/logout")
    assert register(client).status_code == 400
    with app.app_context():
        assert db.session.query(User).count() == 1


def test_login_bad_password_and_safe_redirect(app, client):
    register(client)
    client.post("/auth/logout")
    assert client.post("/auth/login", data={"email": "participant@example.test", "password": "wrong"}).status_code == 401
    response = client.post("/auth/login?next=https://evil.example", data={"email": "participant@example.test", "password": PASSWORD})
    assert response.status_code == 302
    assert response.location == "/dashboard"


def test_role_boundaries_and_login_required(client):
    assert client.get("/dashboard").status_code == 302
    register(client, role="evaluator")
    for path in ["/team", "/project", "/admin/", "/passes/scanner"]:
        assert client.get(path).status_code == 403


def test_invalid_submission_does_not_create_project(app, client):
    register(client)
    assert submit(client, abstract="Too short").status_code == 400
    assert submit(client, category_id="999").status_code == 400
    with app.app_context():
        assert db.session.query(Project).count() == 0


def test_validated_poster_upload_and_owner_only_delivery(app, client):
    register(client)
    assert submit(client, poster=(png(), "../../poster.png")).status_code == 302
    with app.app_context():
        project = db.session.scalar(db.select(Project))
        project_id = project.id
        assert "/" not in project.poster_filename
        assert project.poster_filename.endswith(".png")
    response = client.get(f"/posters/{project_id}")
    assert response.status_code == 200
    assert response.data.startswith(b"\x89PNG")
    assert response.headers["Cache-Control"] == "no-store"
    client.post("/auth/logout")
    register(client, email="someoneelse@example.test")
    assert client.get(f"/posters/{project_id}").status_code == 403


def test_fake_image_rejected(app, client):
    register(client)
    assert submit(client, poster=(io.BytesIO(b"<script>alert(1)</script>"), "poster.png")).status_code == 400
    with app.app_context():
        assert db.session.query(Project).count() == 0


def test_approved_project_and_team_locked(app, client, admin, login):
    register(client)
    submit(client)
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.role == "exhibitor"))
        user_id, project_id = user.id, user.team.project.id
    login(admin)
    assert client.post(f"/admin/applications/{project_id}/review", data={"status": "approved", "comment": "Ready for exhibition."}).status_code == 302
    login(user_id)
    assert submit(client, title="Changed after approval").status_code == 302
    client.post("/team", data={"name": "Changed team", "institution": "New university"})
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.title == "Smart water monitoring system"
        assert project.team.name != "Changed team"
        assert project.status == "approved"


def test_complete_registration_to_checkin_and_pdf_flow(app, client, admin, login):
    register(client)
    submit(client)
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.role == "exhibitor"))
        user_id, project_id = user.id, user.team.project.id
        booth_id = db.session.scalar(db.select(Booth)).id
    assert client.get("/passes/token").status_code == 403
    login(admin)
    assert client.post(f"/admin/applications/{project_id}/review", data={"status": "approved", "comment": "Approved."}).status_code == 302
    assert client.post(f"/admin/applications/{project_id}/booth", data={"booth_id": booth_id}).status_code == 302
    login(user_id)
    token_response = client.get("/passes/token")
    assert token_response.status_code == 200
    token = token_response.json["token"]
    assert client.get("/passes/download").data.startswith(b"%PDF")
    assert client.get("/passes/certificate").data.startswith(b"%PDF")
    login(admin)
    result = client.post("/passes/check-in", json={"token": token})
    assert result.status_code == 200 and result.json["ok"]
    assert client.post("/passes/check-in", json={"token": token}).json["duplicate"] is True
    report = client.get("/admin/report.csv")
    assert report.status_code == 200
    assert b"Smart water monitoring system" in report.data
    with app.app_context():
        assert db.session.query(CheckIn).count() == 1


def test_rejected_submission_can_be_revised(app, client, admin, login):
    register(client)
    submit(client)
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.role == "exhibitor"))
        user_id, project_id = user.id, user.team.project.id
    login(admin)
    client.post(f"/admin/applications/{project_id}/review", data={"status": "rejected", "comment": "Please explain your evaluation."})
    login(user_id)
    assert submit(client, title="Improved water monitoring system").status_code == 302
    with app.app_context():
        project = db.session.get(Project, project_id)
        assert project.status == "pending"
        assert project.review_comment == ""


def test_csrf_protects_account_and_json_actions(app, client, admin, login):
    app.config["WTF_CSRF_ENABLED"] = True
    assert register(client).status_code == 400
    login(admin)
    assert client.post("/passes/check-in", json={"token": "forged"}).status_code == 400
    assert client.post("/auth/logout").status_code == 400


def test_initialization_is_repeatable_and_does_not_reset_applications(app, client):
    register(client)
    submit(client)
    runner = app.test_cli_runner()
    assert runner.invoke(args=["init-db"]).exit_code == 0
    assert runner.invoke(args=["init-db"]).exit_code == 0
    with app.app_context():
        assert db.session.query(Project).count() == 1
        assert db.session.query(Category).count() == 4
        assert db.session.query(Booth).count() == 20


def test_health_reports_database_connection(client):
    assert client.get("/health").json == {"status": "ok", "database": "connected"}
