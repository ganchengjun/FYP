import os

import pytest

from irice import create_app
from irice.extensions import db
from irice.cli import seed_defaults
from irice.models import User
from sqlalchemy.engine import make_url

# All fixtures, including module-specific ones, inherit this fail-closed guard.
_test_url = os.environ.get("IRICE_TEST_DATABASE_URL")
if _test_url and not (make_url(_test_url).database or "").endswith("_test"):
    raise RuntimeError("Refusing to reset a database whose name does not end in _test")


@pytest.fixture
def app(tmp_path):
    # Integration runs explicitly supply an isolated MySQL *test* database.
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-key-not-for-deployment",
        "WTF_CSRF_ENABLED": False,
        "SQLALCHEMY_DATABASE_URI": os.environ.get("IRICE_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}"),
        "UPLOAD_FOLDER": str(tmp_path / "posters"),
    })
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_defaults()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(app):
    with app.app_context():
        user = User(name="Test organizer", email="organizer@example.test", role="admin", approval_status="approved")
        user.set_password("Testing-password-123")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def login(client):
    def sign_in(user_id):
        with client.session_transaction() as session:
            session.clear()
            session["user_id"] = user_id
    return sign_in
