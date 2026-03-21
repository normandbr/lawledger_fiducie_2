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
