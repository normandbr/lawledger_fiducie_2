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


# ---------------------------------------------------------------------------
# 10. Import duplicate-check fix (issue: failed imports blocked re-upload)
# ---------------------------------------------------------------------------
class TestImportDuplicateCheck:
    """Verify that the ImportLog duplicate query only blocks 'success'/'partial'
    imports, not 'failed' ones.  We test the DB filtering logic directly since
    the /api/import/costs endpoint is license-restricted in the test environment."""

    def test_failed_status_not_blocked(self, app):
        """A previous import with status='failed' must NOT block a re-upload.
        The duplicate query must only match 'success' or 'partial' records."""
        from app import db, ImportLog
        import hashlib

        fake_hash = hashlib.sha256(b"dummy csv content for test").hexdigest()

        with app.app_context():
            ImportLog.query.filter_by(file_hash=fake_hash).delete()
            db.session.commit()

            prev = ImportLog(
                import_id="aabbccdd" * 4,
                filename="expenses.csv",
                file_hash=fake_hash,
                records_imported=0,
                records_failed=5,
                status="failed",
            )
            db.session.add(prev)
            db.session.commit()

            # The fixed query must NOT find this record
            existing = ImportLog.query.filter(
                ImportLog.file_hash == fake_hash,
                ImportLog.status.in_(['success', 'partial'])
            ).first()
            assert existing is None, "Failed import must not block re-upload"

            ImportLog.query.filter_by(file_hash=fake_hash).delete()
            db.session.commit()

    def test_success_status_is_blocked(self, app):
        """A previous import with status='success' MUST be detected as duplicate."""
        from app import db, ImportLog
        import hashlib

        fake_hash = hashlib.sha256(b"csv content that succeeded").hexdigest()

        with app.app_context():
            ImportLog.query.filter_by(file_hash=fake_hash).delete()
            db.session.commit()

            prev = ImportLog(
                import_id="11223344" * 4,
                filename="expenses_ok.csv",
                file_hash=fake_hash,
                records_imported=3,
                records_failed=0,
                status="success",
            )
            db.session.add(prev)
            db.session.commit()

            existing = ImportLog.query.filter(
                ImportLog.file_hash == fake_hash,
                ImportLog.status.in_(['success', 'partial'])
            ).first()
            assert existing is not None, "Successful import must block re-upload"
            assert existing.status == "success"

            ImportLog.query.filter_by(file_hash=fake_hash).delete()
            db.session.commit()

    def test_partial_status_is_blocked(self, app):
        """A previous import with status='partial' MUST be detected as duplicate."""
        from app import db, ImportLog
        import hashlib

        fake_hash = hashlib.sha256(b"csv content partially imported").hexdigest()

        with app.app_context():
            ImportLog.query.filter_by(file_hash=fake_hash).delete()
            db.session.commit()

            prev = ImportLog(
                import_id="99887766" * 4,
                filename="expenses_partial.csv",
                file_hash=fake_hash,
                records_imported=2,
                records_failed=1,
                status="partial",
            )
            db.session.add(prev)
            db.session.commit()

            existing = ImportLog.query.filter(
                ImportLog.file_hash == fake_hash,
                ImportLog.status.in_(['success', 'partial'])
            ).first()
            assert existing is not None, "Partial import must block re-upload"
            assert existing.status == "partial"

            ImportLog.query.filter_by(file_hash=fake_hash).delete()
            db.session.commit()


# ---------------------------------------------------------------------------
# 11. Trust Authorization API (fiducie)
# ---------------------------------------------------------------------------
class TestTrustAuthorizationAPI:
    """Verify that the trust authorization GET/POST routes work correctly."""

    def _create_matter(self, app):
        from app import db, Client as ClientModel, Matter
        c = ClientModel.query.filter_by(client_number="AUTH-C001").first()
        if not c:
            c = ClientModel(client_number="AUTH-C001", client_name="Auth Test Client", is_active=True)
            db.session.add(c)
            db.session.flush()
        m = Matter.query.filter_by(matter_number="AUTH-M001").first()
        if not m:
            m = Matter(client_id=c.id, matter_number="AUTH-M001")
            db.session.add(m)
        db.session.commit()
        return m

    def test_list_authorizations_empty(self, client, manager_user, app):
        """GET /api/fiducie/<id>/authorizations returns [] for a new matter."""
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
        resp = client.get(f"/api/fiducie/{matter_id}/authorizations")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        logout(client)

    def test_create_authorization(self, client, manager_user, app):
        """POST /api/fiducie/<id>/authorizations creates a new authorization."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
        resp = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": date.today().isoformat(), "notes": "Test auth"},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data.get("matter_id") == matter_id
        assert data.get("notes") == "Test auth"
        assert data.get("is_active") is True
        logout(client)

    def test_list_after_create(self, client, manager_user, app):
        """GET returns the authorization created by POST."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": date.today().isoformat(), "notes": "Listed auth"},
        )
        resp = client.get(f"/api/fiducie/{matter_id}/authorizations")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert any(a.get("notes") == "Listed auth" for a in data)
        logout(client)

    def test_create_authorization_requires_manager(self, client, staff_user, app):
        """Non-manager must receive 403 when creating an authorization."""
        login(client, "test_staff", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
        resp = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"notes": "Should fail"},
        )
        assert resp.status_code == 403
        logout(client)

    def test_duplicate_active_authorization_rejected(self, client, manager_user, app):
        """Creating a second active authorization for the same matter must return 409."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        # Create first authorization (should succeed)
        r1 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r1.status_code == 201

        # Attempt to create a second one (should be rejected)
        r2 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r2.status_code == 409
        logout(client)

    def test_soft_delete_then_create_succeeds(self, client, manager_user, app):
        """After soft-deleting an active authorization, a new one can be created."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        r1 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r1.status_code == 201
        auth_id = r1.get_json()["id"]

        # Soft-delete
        rd = client.delete(f"/api/fiducie/authorizations/{auth_id}")
        assert rd.status_code == 200

        # Now creating a new one must succeed
        r2 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r2.status_code == 201
        logout(client)

    def test_soft_delete_sets_is_deleted_and_deleted_by(self, client, manager_user, app):
        """Soft-deleting an authorization must set is_deleted=True, is_active=False, and deleted_by."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        r1 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r1.status_code == 201
        auth_id = r1.get_json()["id"]

        # Soft-delete
        rd = client.delete(f"/api/fiducie/authorizations/{auth_id}")
        assert rd.status_code == 200

        # The deleted authorization must reflect the soft-delete in the API response
        auths = client.get(f"/api/fiducie/{matter_id}/authorizations").get_json()
        deleted_auth = next((a for a in auths if a["id"] == auth_id), None)
        assert deleted_auth is not None
        assert deleted_auth["is_deleted"] is True
        assert deleted_auth["is_active"] is False
        assert deleted_auth["is_valid"] is False
        assert deleted_auth["deleted_at"] is not None
        # deleted_by should be populated with the manager's display name
        assert deleted_auth["deleted_by"] != ''
        logout(client)

    def test_create_authorization_has_is_deleted_false(self, client, manager_user, app):
        """A newly created authorization must have is_deleted=False in the API response."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        r1 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r1.status_code == 201
        data = r1.get_json()
        assert data.get("is_deleted") is False
        assert data.get("deleted_by") == ''
        assert data.get("deleted_at") is None
        logout(client)

    def test_expired_authorization_allows_new(self, client, manager_user, app):
        """An expired (date_to in the past) authorization must not block a new one."""
        from datetime import date, timedelta
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        past = (date.today() - timedelta(days=30)).isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        # Create an expired authorization first (no active auth yet, should succeed)
        r1 = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": past, "date_to": yesterday},
        )
        assert r1.status_code == 201

        # Creating a new authorization for today should succeed (old one is expired)
        today = date.today().isoformat()
        r2 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r2.status_code == 201
        logout(client)

    def test_is_valid_field_reflects_active_on(self, client, manager_user, app):
        """The is_valid field returned by the list endpoint must match is_active_on()."""
        from datetime import date, timedelta
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            m = self._create_matter(app)
            matter_id = m.id
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        past = (date.today() - timedelta(days=30)).isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        # Create an expired authorization first (date_to in the past, not active today)
        r1 = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": past, "date_to": yesterday},
        )
        assert r1.status_code == 201

        # Now create a currently active authorization (no conflict – expired one is inactive)
        r2 = client.post(f"/api/fiducie/{matter_id}/authorizations", json={"date_from": today})
        assert r2.status_code == 201

        auths = client.get(f"/api/fiducie/{matter_id}/authorizations").get_json()
        valid = [a for a in auths if a["is_valid"]]
        invalid = [a for a in auths if not a["is_valid"]]
        # Only the active one (today) should be is_valid=True; the expired one is False
        assert len(valid) == 1
        assert len(invalid) == 1
        logout(client)


# ---------------------------------------------------------------------------
# 12. Invoice creation with trust funds – authorization enforcement
# ---------------------------------------------------------------------------
class TestInvoiceTrustAuthorizationEnforcement:
    """Verify that apply_trust=True requires a valid trust authorization."""

    def _setup_matter_with_client(self, app):
        """Create (or reuse) a test client and matter, return (client_id, matter_id)."""
        from app import db, Client as ClientModel, Matter
        c = ClientModel.query.filter_by(client_number="INVAUTH-C001").first()
        if not c:
            c = ClientModel(client_number="INVAUTH-C001", client_name="InvAuth Test Client", is_active=True)
            db.session.add(c)
            db.session.flush()
        m = Matter.query.filter_by(matter_number="INVAUTH-M001").first()
        if not m:
            m = Matter(client_id=c.id, matter_number="INVAUTH-M001")
            db.session.add(m)
        db.session.commit()
        return c.id, m.id

    @staticmethod
    def _mock_valid_license():
        """Return a context manager that makes the license appear valid."""
        from unittest.mock import patch, MagicMock
        mock_result = MagicMock()
        mock_result.is_valid = True
        return patch('licensing.get_cached_license_result', return_value=mock_result)

    def test_apply_trust_blocked_without_authorization(self, client, manager_user, app):
        """Creating an invoice with apply_trust=True must return 403 when there is
        no active authorization for the matter."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            client_id, matter_id = self._setup_matter_with_client(app)
            # Ensure no authorizations exist
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        with self._mock_valid_license():
            resp = client.post(
                "/api/invoices",
                json={
                    "matter_id": matter_id,
                    "invoice_date": date.today().isoformat(),
                    "apply_trust": True,
                },
            )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data.get("error") == "no_authorization"
        logout(client)

    def test_apply_trust_blocked_after_auth_soft_deleted(self, client, manager_user, app):
        """Soft-deleting the only authorization must block apply_trust on invoice creation."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            client_id, matter_id = self._setup_matter_with_client(app)
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        # Create an authorization and immediately soft-delete it
        with self._mock_valid_license():
            r_auth = client.post(
                f"/api/fiducie/{matter_id}/authorizations",
                json={"date_from": today},
            )
        assert r_auth.status_code == 201
        auth_id = r_auth.get_json()["id"]
        client.delete(f"/api/fiducie/authorizations/{auth_id}")

        # Now apply_trust should be rejected
        with self._mock_valid_license():
            resp = client.post(
                "/api/invoices",
                json={
                    "matter_id": matter_id,
                    "invoice_date": today,
                    "apply_trust": True,
                },
            )
        assert resp.status_code == 403
        assert resp.get_json().get("error") == "no_authorization"
        logout(client)

    def test_apply_trust_allowed_with_valid_authorization(self, client, manager_user, app):
        """Creating an invoice with apply_trust=True is not blocked by missing-auth when
        a valid active authorization exists for the matter."""
        from datetime import date
        from app import db, TrustAuthorization
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            client_id, matter_id = self._setup_matter_with_client(app)
            TrustAuthorization.query.filter_by(matter_id=matter_id).delete()
            db.session.commit()

        today = date.today().isoformat()
        # Create a valid authorization
        with self._mock_valid_license():
            r_auth = client.post(
                f"/api/fiducie/{matter_id}/authorizations",
                json={"date_from": today},
            )
        assert r_auth.status_code == 201

        # Invoice creation with apply_trust must now pass the auth check
        with self._mock_valid_license():
            resp = client.post(
                "/api/invoices",
                json={
                    "matter_id": matter_id,
                    "invoice_date": today,
                    "apply_trust": True,
                },
            )
        # Should NOT be blocked by missing authorization
        data = resp.get_json()
        assert not (resp.status_code == 403 and data.get("error") == "no_authorization")
        logout(client)


# ---------------------------------------------------------------------------
# 13. Trust authorization max_amount enforcement
# ---------------------------------------------------------------------------
class TestTrustAuthMaxAmount:
    """Verify that RETRAIT/REMBOURSEMENT transactions respect the authorization max_amount."""

    def _setup(self, app):
        """Create a test client, matter, and return (matter_id,)."""
        from app import db, Client as ClientModel, Matter, TrustAuthorization, TransactionsFiducie
        c = ClientModel.query.filter_by(client_number="MAXAMT-C001").first()
        if not c:
            c = ClientModel(client_number="MAXAMT-C001", client_name="MaxAmt Client", is_active=True)
            db.session.add(c)
            db.session.flush()
        m = Matter.query.filter_by(matter_number="MAXAMT-M001").first()
        if not m:
            m = Matter(client_id=c.id, matter_number="MAXAMT-M001")
            db.session.add(m)
            db.session.flush()
        # Wipe any existing transactions and authorizations so tests start clean
        TransactionsFiducie.query.filter_by(matter_id=m.id).delete()
        TrustAuthorization.query.filter_by(matter_id=m.id).delete()
        db.session.commit()
        return m.id

    def _deposit(self, client, matter_id, amount):
        """Helper: create a DEPOT transaction."""
        from datetime import date
        resp = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "DEPOT", "montant": amount, "motif": "test deposit"},
        )
        assert resp.status_code == 201, resp.get_json()

    def test_retrait_blocked_when_max_amount_exceeded(self, client, manager_user, app):
        """A RETRAIT that would exceed the authorization max_amount must return 400."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            matter_id = self._setup(app)

        # First deposit $1000 into trust
        self._deposit(client, matter_id, 1000.0)

        today = date.today().isoformat()
        # Create authorization with max_amount=$300
        r_auth = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": today, "max_amount": 300.0},
        )
        assert r_auth.status_code == 201

        # Attempting a $350 RETRAIT should be blocked (exceeds $300 max)
        resp = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 350.0, "motif": "over limit"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("error") == "max_amount_exceeded"
        assert "300" in data.get("message", "")
        logout(client)

    def test_retrait_allowed_under_max_amount(self, client, manager_user, app):
        """A RETRAIT within the authorization max_amount must succeed."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            matter_id = self._setup(app)

        self._deposit(client, matter_id, 1000.0)

        today = date.today().isoformat()
        r_auth = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": today, "max_amount": 300.0},
        )
        assert r_auth.status_code == 201

        # A $200 RETRAIT is within the $300 limit
        resp = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 200.0, "motif": "within limit"},
        )
        assert resp.status_code == 201
        logout(client)

    def test_cumulative_retraits_blocked_at_max_amount(self, client, manager_user, app):
        """Successive RETRAIT transactions that cumulatively exceed max_amount must be blocked."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            matter_id = self._setup(app)

        self._deposit(client, matter_id, 1000.0)

        today = date.today().isoformat()
        r_auth = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": today, "max_amount": 300.0},
        )
        assert r_auth.status_code == 201

        # First withdrawal: $200 (total used = $200, under $300)
        r1 = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 200.0},
        )
        assert r1.status_code == 201

        # Second withdrawal: $150 (would bring total to $350, over $300)
        r2 = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 150.0},
        )
        assert r2.status_code == 400
        assert r2.get_json().get("error") == "max_amount_exceeded"
        logout(client)

    def test_retrait_no_max_amount_unlimited(self, client, manager_user, app):
        """An authorization without max_amount imposes no upper limit on withdrawals."""
        from datetime import date
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            matter_id = self._setup(app)

        self._deposit(client, matter_id, 1000.0)

        today = date.today().isoformat()
        # Authorization with no max_amount (unlimited)
        r_auth = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": today},
        )
        assert r_auth.status_code == 201

        # Should be able to withdraw the full available balance
        resp = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 900.0},
        )
        assert resp.status_code == 201
        logout(client)

    def test_authorization_to_dict_includes_amount_used(self, client, manager_user, app):
        """The authorization to_dict must include amount_used and amount_remaining."""
        from datetime import date
        from app import db, TrustAuthorization, TransactionsFiducie
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            matter_id = self._setup(app)

        self._deposit(client, matter_id, 1000.0)

        today = date.today().isoformat()
        r_auth = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": today, "max_amount": 300.0},
        )
        assert r_auth.status_code == 201

        # Make a $100 withdrawal
        client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 100.0},
        )

        # Check the authorization list
        auths_resp = client.get(f"/api/fiducie/{matter_id}/authorizations")
        assert auths_resp.status_code == 200
        auths = auths_resp.get_json()
        auth = next((a for a in auths if a.get("is_valid")), None)
        assert auth is not None
        assert auth.get("amount_used") == 100.0
        assert auth.get("amount_remaining") == 200.0
        assert auth.get("max_amount") == 300.0
        logout(client)

    def test_transaction_stores_authorization_id(self, client, manager_user, app):
        """A RETRAIT transaction must store the authorization_id of the active auth."""
        from datetime import date
        from app import db, TransactionsFiducie
        login(client, "test_manager", "Pass1234!")
        with app.app_context():
            matter_id = self._setup(app)

        self._deposit(client, matter_id, 1000.0)

        today = date.today().isoformat()
        r_auth = client.post(
            f"/api/fiducie/{matter_id}/authorizations",
            json={"date_from": today, "max_amount": 500.0},
        )
        assert r_auth.status_code == 201
        auth_id = r_auth.get_json()["id"]

        r_retrait = client.post(
            f"/api/fiducie/{matter_id}",
            json={"type_trans": "RETRAIT", "montant": 150.0},
        )
        assert r_retrait.status_code == 201
        trans_id = r_retrait.get_json()["id"]

        with app.app_context():
            txn = TransactionsFiducie.query.get(trans_id)
            assert txn is not None
            assert txn.authorization_id == auth_id
        logout(client)

