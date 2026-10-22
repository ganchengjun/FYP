"""MySQL regression: current locking reads must override older lazy snapshots."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from flask import g

from irice import participant
from irice.extensions import db
from irice.models import Project, Team, User


def test_mysql_simultaneous_first_submissions_do_not_duplicate_or_fail(app, monkeypatch):
    with app.app_context():
        if db.engine.dialect.name != "mysql":
            pytest.skip("Requires MySQL repeatable-read and row locks")
        user = User(name="Concurrent exhibitor", email="concurrent@example.test", role="exhibitor", password_hash="unused")
        user.team = Team(name="Concurrent team", institution="Southern University College")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    rendezvous = Barrier(2, timeout=10)
    original = participant.exhibitor_team

    def simultaneous_snapshots(lock=False):
        if lock:
            assert g.user.team is not None  # establish both old snapshots
            rendezvous.wait()
        return original(lock=lock)

    monkeypatch.setattr(participant, "exhibitor_team", simultaneous_snapshots)

    def submit(index):
        with app.test_client() as client:
            with client.session_transaction() as session:
                session["user_id"] = user_id
            response = client.post("/project", data={
                "title": f"Concurrent submission {index}", "category_id": "1",
                "abstract": "A meaningful project abstract describing a reliable monitoring prototype and its intended community evaluation.",
                "requirements": "One table",
            })
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(submit, [1, 2]))
    assert statuses == [302, 302]
    with app.app_context():
        assert db.session.query(Project).count() == 1
        assert db.session.scalar(db.select(Project)).status == "pending"
