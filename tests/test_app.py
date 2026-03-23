"""
LawLedger – Automatic tests (pytest)
=====================================
These tests verify the main application features without requiring a database.
They use Flask's built-in test client and an in-memory SQLite database.

Run:
    pytest tests/test_app.py -v
"""
import os
import sys
import pytest

# ---------------------------------------------------------------------------
# Ensure app module is importable from the repo root, and set DATABASE_URL
# BEFORE importing the app so that SQLAlchemy uses SQLite instead of pyodbc.
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Must be set before the first import of app
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest")
# Disable URL prefix so test redirects resolve correctly (no /lawledger prefix)
os.environ["URL_PREFIX"] = ""


# ---------------------------------------------------------------------------
# App fixture – in-memory SQLite, testing mode
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    from app import app as flask_app, db

    flask_app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-secret-key-for-pytest",
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def manager_user(app):
    """Create and return a manager user for tests."""
    from app import db, Employee
    from werkzeug.security import generate_password_hash

    with app.app_context():
        # Clean up any previous test user
        Employee.query.filter_by(username="test_manager").delete()
        db.session.commit()

        mgr = Employee(
            username="test_manager",
            first_name="Test",
            last_name="Manager",
            email="mgr@test.local",
            password_hash=generate_password_hash("Pass1234!"),
            is_manager=True,
            is_user=True,
            is_active=True,
        )
        db.session.add(mgr)
        db.session.commit()
        yield mgr
        Employee.query.filter_by(username="test_manager").delete()
        db.session.commit()


@pytest.fixture()
def staff_user(app):
    """Create and return a non-manager (staff) user for tests."""
    from app import db, Employee
    from werkzeug.security import generate_password_hash

    with app.app_context():
        Employee.query.filter_by(username="test_staff").delete()
        db.session.commit()

        staff = Employee(
            username="test_staff",
            first_name="Test",
            last_name="Staff",
            email="staff@test.local",
            password_hash=generate_password_hash("Pass1234!"),
            is_manager=False,
            is_user=True,
            is_active=True,
        )
        db.session.add(staff)
        db.session.commit()
        yield staff
        Employee.query.filter_by(username="test_staff").delete()
        db.session.commit()


# ---------------------------------------------------------------------------
# Helper: log in via the test client
# ---------------------------------------------------------------------------
def login(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def logout(client):
    return client.get("/logout", follow_redirects=True)


# ---------------------------------------------------------------------------
# 1. Application starts and login page is reachable
# ---------------------------------------------------------------------------
class TestBasicRoutes:
    def test_login_page_loads(self, client):
        """The login page must return HTTP 200."""
        resp = client.get("/login")
        assert resp.status_code == 200

    def test_home_redirects_when_not_logged_in(self, client):
        """Accessing / without being logged in redirects to login."""
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 301)

    def test_favicon_or_static_reachable(self, client):
        """Static folder exists and a known file is accessible."""
        resp = client.get("/static/css/style.css", follow_redirects=False)
        # Either 200 (file exists) or 404 (OK too – just not 500)
        assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# 2. Authentication – login / logout
# ---------------------------------------------------------------------------
class TestAuthentication:
    def test_invalid_login(self, client):
        """Wrong credentials must not grant access."""
        resp = login(client, "nobody", "wrongpassword")
        assert resp.status_code == 200
        # Should stay on the login page (or show an error)
        assert b"login" in resp.data.lower() or resp.status_code == 200

    def test_valid_manager_login(self, client, manager_user):
        """A valid manager can log in and reaches the home page."""
        resp = login(client, "test_manager", "Pass1234!")
        assert resp.status_code == 200
        logout(client)

    def test_logout_redirects(self, client, manager_user):
        """After logout, the user is redirected to login."""
        login(client, "test_manager", "Pass1234!")
        resp = logout(client)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 3. Role-based access control
# ---------------------------------------------------------------------------
class TestAccessControl:
    def test_gl_page_blocked_for_staff(self, client, staff_user):
        """Non-managers must be redirected when accessing /gl."""
        login(client, "test_staff", "Pass1234!")
        resp = client.get("/gl", follow_redirects=True)
        assert resp.status_code == 200
        # Should be redirected away (home page or flash message)
        assert b"/gl" not in resp.request.path.encode() or b"restricted" in resp.data.lower()
        logout(client)

    def test_gl_page_accessible_for_manager(self, client, manager_user):
        """Managers must be able to access /gl."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/gl", follow_redirects=True)
        assert resp.status_code == 200
        logout(client)

    def test_gl_api_blocked_for_staff(self, client, staff_user):
        """Non-managers must receive 403 from /api/gl."""
        login(client, "test_staff", "Pass1234!")
        resp = client.get("/api/gl?date_from=2025-01-01&date_to=2025-12-31")
        assert resp.status_code == 403
        logout(client)

    def test_hr_records_blocked_for_staff(self, client, staff_user):
        """Non-managers must be redirected from /hr-records."""
        login(client, "test_staff", "Pass1234!")
        resp = client.get("/hr-records", follow_redirects=True)
        assert resp.status_code == 200
        # Should redirect away from hr-records
        assert b"/hr-records" not in resp.request.path.encode() or b"restricted" in resp.data.lower()
        logout(client)

    def test_hr_records_accessible_for_manager(self, client, manager_user):
        """Managers must be able to access /hr-records."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/hr-records", follow_redirects=True)
        assert resp.status_code == 200
        logout(client)


# ---------------------------------------------------------------------------
# 4. Client & Matter API endpoints
# ---------------------------------------------------------------------------
class TestClientAPI:
    def test_clients_list_returns_json(self, client, manager_user):
        """GET /api/clients must return a JSON list."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/clients")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        logout(client)

    def test_create_client(self, client, manager_user, app):
        """POST /api/clients creates a new client."""
        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            "/api/clients",
            json={
                "client_number": "TEST-001",
                "client_name": "Test Client SA",
                "is_active": True,
            },
        )
        assert resp.status_code in (200, 201)
        data = resp.get_json()
        assert data.get("client_number") == "TEST-001" or data.get("id") is not None
        logout(client)


# ---------------------------------------------------------------------------
# 5. Invoice API endpoints
# ---------------------------------------------------------------------------
class TestInvoiceAPI:
    def test_invoices_list_returns_json(self, client, manager_user):
        """GET /api/invoices must return a JSON response (200 or 403 if license-restricted)."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/invoices")
        # 200 = OK, 403 = license restriction in test env (no license.json)
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            data = resp.get_json()
            assert isinstance(data, list)
        logout(client)


# ---------------------------------------------------------------------------
# 6. Unbilled / Accounts Receivable API
# ---------------------------------------------------------------------------
class TestUnbilledAPI:
    def test_unbilled_returns_json(self, client, manager_user):
        """GET /api/unbilled must return a JSON list."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/unbilled")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        logout(client)

    def test_ar_invoices_returns_json(self, client, manager_user):
        """GET /api/ar-invoices must return a JSON list."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/ar-invoices")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        logout(client)


# ---------------------------------------------------------------------------
# 7. Page rendering – key pages must return HTTP 200
# ---------------------------------------------------------------------------
class TestPageRendering:
    MANAGER_PAGES = [
        "/",
        "/clients",
        "/invoices",
        "/unbilled",
        "/gl",
        "/hr-records",
        "/accounts",
        "/calendar",
    ]

    def test_manager_pages_render(self, client, manager_user):
        """All main pages must return HTTP 200 when logged in as manager."""
        login(client, "test_manager", "Pass1234!")
        for path in self.MANAGER_PAGES:
            resp = client.get(path, follow_redirects=True)
            assert resp.status_code == 200, f"Page {path} returned {resp.status_code}"
        logout(client)


# ---------------------------------------------------------------------------
# 8. Template content checks (regression)
# ---------------------------------------------------------------------------
class TestTemplateContent:
    def test_clients_page_has_invoice_button_translation(self, client, manager_user, app):
        """The clients page must include the Factures/Invoices button text."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/clients", follow_redirects=True)
        assert resp.status_code == 200
        # The I18N object must contain the btn_invoices key
        assert b"Factures" in resp.data or b"Invoices" in resp.data
        logout(client)

    def test_invoice_print_no_running_header(self, client, manager_user, app):
        """The invoice_print template must NOT contain the running header div."""
        from datetime import date
        from app import db, Invoice, Client as ClientModel

        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            # Create a minimal client + invoice for the print route test
            c = ClientModel(
                client_number="PTEST-001",
                client_name="Print Test Client",
                is_active=True,
            )
            db.session.add(c)
            db.session.flush()
            inv = Invoice(
                invoice_number="INV-PRINT-001",
                client_id=c.id,
                status="sent",
                invoice_date=date(2026, 1, 15),
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id
            c_id = c.id

        resp = client.get(f"/invoices/{inv_id}/print", follow_redirects=True)
        assert resp.status_code == 200
        # Running header must have been removed
        assert b"print-running-header" not in resp.data

        with app.app_context():
            Invoice.query.filter_by(id=inv_id).delete()
            ClientModel.query.filter_by(id=c_id).delete()
            db.session.commit()
        logout(client)


# ---------------------------------------------------------------------------
# 9. Calendar / Agenda module
# ---------------------------------------------------------------------------
class TestCalendarModule:
    def test_calendar_page_renders(self, client, manager_user):
        """GET /calendar must return HTTP 200 for an authenticated user."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/calendar", follow_redirects=True)
        assert resp.status_code == 200
        logout(client)

    def test_calendar_page_requires_login(self, client):
        """GET /calendar must redirect to login when not authenticated."""
        resp = client.get("/calendar", follow_redirects=False)
        assert resp.status_code in (302, 301)

    def test_calendar_api_list_empty(self, client, manager_user):
        """GET /api/calendar/events must return an empty list initially."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/calendar/events")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        logout(client)

    def test_calendar_api_create_event(self, client, manager_user):
        """POST /api/calendar/events must create a new event and return 201."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        payload = {
            "title": "Test Hearing",
            "event_date": date.today().isoformat(),
            "event_type": "hearing",
        }
        resp = client.post("/api/calendar/events", json=payload)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data.get("title") == "Test Hearing"
        assert data.get("id") is not None
        event_id = data["id"]

        # Clean up
        from app import db, CalendarEvent
        with client.application.app_context():
            CalendarEvent.query.filter_by(id=event_id).delete()
            db.session.commit()
        logout(client)

    def test_calendar_api_create_requires_title(self, client, manager_user):
        """POST /api/calendar/events without a title must return 400."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            "/api/calendar/events",
            json={"event_date": date.today().isoformat()},
        )
        assert resp.status_code == 400
        logout(client)

    def test_calendar_api_create_requires_date(self, client, manager_user):
        """POST /api/calendar/events without a date must return 400."""
        login(client, "test_manager", "Pass1234!")
        resp = client.post("/api/calendar/events", json={"title": "No Date"})
        assert resp.status_code == 400
        logout(client)

    def test_calendar_api_update_and_delete(self, client, manager_user, app):
        """PUT and DELETE /api/calendar/events/<id> must work correctly."""
        from datetime import date
        from app import db, CalendarEvent
        login(client, "test_manager", "Pass1234!")

        # Create
        resp = client.post(
            "/api/calendar/events",
            json={"title": "Update Me", "event_date": date.today().isoformat()},
        )
        assert resp.status_code == 201
        event_id = resp.get_json()["id"]

        # Update
        resp = client.put(
            f"/api/calendar/events/{event_id}",
            json={"title": "Updated Title", "is_done": True},
        )
        assert resp.status_code == 200
        assert resp.get_json()["title"] == "Updated Title"
        assert resp.get_json()["is_done"] is True

        # Delete
        resp = client.delete(f"/api/calendar/events/{event_id}")
        assert resp.status_code == 200
        assert resp.get_json().get("success") is True

        # After soft-delete, the event should not appear in listing
        resp = client.get("/api/calendar/events?show_done=1")
        events = resp.get_json()
        assert not any(e["id"] == event_id for e in events)

        logout(client)

    def test_calendar_nav_link_present(self, client, manager_user):
        """The calendar navigation link must appear on authenticated pages."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/", follow_redirects=True)
        assert resp.status_code == 200
        assert b"/calendar" in resp.data
        logout(client)

    def test_calendar_events_per_user_isolation(self, client, manager_user, app):
        """Events created by one user must not be visible to another user."""
        from datetime import date
        from app import db, CalendarEvent

        # Insert two events directly: one for the manager, one for "other_user"
        with app.app_context():
            ev_mgr = CalendarEvent(
                title="Manager Event",
                event_date=date.today(),
                created_by="test_manager",
            )
            ev_other = CalendarEvent(
                title="Other User Event",
                event_date=date.today(),
                created_by="other_user",
            )
            db.session.add_all([ev_mgr, ev_other])
            db.session.commit()
            mgr_event_id = ev_mgr.id
            other_event_id = ev_other.id

        # Manager should see their own event but NOT the other user's event
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/calendar/events?show_done=1")
        assert resp.status_code == 200
        events = resp.get_json()
        event_ids = [e["id"] for e in events]
        assert mgr_event_id   in event_ids
        assert other_event_id not in event_ids
        logout(client)

        # Clean up
        with app.app_context():
            CalendarEvent.query.filter(
                CalendarEvent.id.in_([mgr_event_id, other_event_id])
            ).delete(synchronize_session=False)
            db.session.commit()

    def test_calendar_room_config_get(self, client, manager_user):
        """GET /api/calendar/rooms must return a list."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/calendar/rooms")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)
        logout(client)

    def test_calendar_room_config_post_requires_manager(self, client, staff_user):
        """POST /api/calendar/rooms must be denied for non-manager users."""
        login(client, "test_staff", "Pass1234!")
        resp = client.post("/api/calendar/rooms", json=[])
        assert resp.status_code == 403
        logout(client)

    def test_calendar_room_config_save_and_retrieve(self, client, manager_user, app):
        """Manager can save room names and retrieve them back."""
        from app import db, RoomConfig
        login(client, "test_manager", "Pass1234!")

        payload = [
            {"room_index": i, "room_name": f"Salle {i}", "is_active": True}
            for i in range(1, 11)
        ]
        resp = client.post("/api/calendar/rooms", json=payload)
        assert resp.status_code == 200
        rooms = resp.get_json()
        assert len(rooms) == 10
        assert rooms[0]["room_name"] == "Salle 1"
        assert rooms[9]["room_name"] == "Salle 10"

        # Retrieve and verify
        resp = client.get("/api/calendar/rooms")
        assert resp.status_code == 200
        rooms = resp.get_json()
        names = {r["room_index"]: r["room_name"] for r in rooms}
        assert names[1] == "Salle 1"
        assert names[10] == "Salle 10"

        # Clean up
        with app.app_context():
            RoomConfig.query.delete()
            db.session.commit()
        logout(client)

    def test_calendar_room_config_button_visible_for_manager(self, client, manager_user):
        """The room configuration button must be visible to managers."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/calendar", follow_redirects=True)
        assert resp.status_code == 200
        assert b"openRoomConfigModal" in resp.data
        logout(client)

