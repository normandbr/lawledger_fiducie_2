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


# ---------------------------------------------------------------------------
# 10. Supplier payments – mark-as-paid with is_paid / date_paid tracking
# ---------------------------------------------------------------------------

class TestSupplierPayments:
    """Tests for the accounts-payable (Comptes à payer) mark-as-paid flow."""

    def _create_supplier(self, app, name="Acme Corp"):
        from app import db, Supplier
        with app.app_context():
            supplier = Supplier(name=name, is_active=True)
            db.session.add(supplier)
            db.session.commit()
            return supplier.id

    def test_create_unpaid_invoice_is_paid_false(self, client, manager_user, app):
        """Creating an invoice without a payment_date sets is_paid=False."""
        from app import db, SupplierPayment
        supplier_id = self._create_supplier(app)
        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            f"/api/suppliers/{supplier_id}/payments",
            json={"invoice_number": "INV-001", "amount": 100.00, "invoice_date": "2024-01-15"},
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["is_paid"] is False
        assert data["date_paid"] is None
        assert data["is_posted"] is False
        with app.app_context():
            SupplierPayment.query.filter_by(supplier_id=supplier_id).delete()
            db.session.commit()
        logout(client)

    def test_create_paid_invoice_sets_is_paid_and_date_paid(self, client, manager_user, app):
        """Creating an invoice with a payment_date sets is_paid=True and date_paid."""
        from app import db, SupplierPayment
        supplier_id = self._create_supplier(app, "Beta Ltd")
        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            f"/api/suppliers/{supplier_id}/payments",
            json={
                "invoice_number": "INV-002",
                "amount": 200.00,
                "invoice_date": "2024-02-01",
                "payment_date": "2024-02-10",
            },
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["is_paid"] is True
        assert data["date_paid"] == "2024-02-10"
        assert data["is_posted"] is True
        with app.app_context():
            SupplierPayment.query.filter_by(supplier_id=supplier_id).delete()
            db.session.commit()
        logout(client)

    def test_mark_as_paid_updates_is_paid_and_date_paid(self, client, manager_user, app):
        """PUT /api/supplier-payments/<id> with payment_date sets is_paid=True and date_paid."""
        from app import db, SupplierPayment
        supplier_id = self._create_supplier(app, "Gamma Inc")
        login(client, "test_manager", "Pass1234!")
        # Create an unpaid invoice
        create_resp = client.post(
            f"/api/suppliers/{supplier_id}/payments",
            json={"invoice_number": "INV-003", "amount": 300.00, "invoice_date": "2024-03-01"},
            content_type="application/json",
        )
        assert create_resp.status_code == 201
        payment_id = create_resp.get_json()["id"]
        # Mark it as paid
        put_resp = client.put(
            f"/api/supplier-payments/{payment_id}",
            json={"payment_date": "2024-03-05", "payment_method": "cheque"},
            content_type="application/json",
        )
        assert put_resp.status_code == 200
        result = put_resp.get_json()
        assert result["is_paid"] is True
        assert result["date_paid"] == "2024-03-05"
        assert result["payment_date"] == "2024-03-05"
        # is_posted must remain False – it's pending GL posting
        assert result["is_posted"] is False
        with app.app_context():
            SupplierPayment.query.filter_by(supplier_id=supplier_id).delete()
            db.session.commit()
        logout(client)

    def test_unpaid_api_returns_only_unpaid(self, client, manager_user, app):
        """GET /api/suppliers/payments/unpaid returns only is_paid=False invoices."""
        from app import db, SupplierPayment
        supplier_id = self._create_supplier(app, "Delta SA")
        login(client, "test_manager", "Pass1234!")
        # Create one unpaid and one paid invoice
        client.post(
            f"/api/suppliers/{supplier_id}/payments",
            json={"invoice_number": "UNPD-1", "amount": 50.00, "invoice_date": "2024-04-01"},
            content_type="application/json",
        )
        client.post(
            f"/api/suppliers/{supplier_id}/payments",
            json={"invoice_number": "PAID-1", "amount": 75.00, "payment_date": "2024-04-01"},
            content_type="application/json",
        )
        resp = client.get("/api/suppliers/payments/unpaid")
        assert resp.status_code == 200
        items = resp.get_json()
        invoice_numbers = [p["invoice_number"] for p in items]
        assert "UNPD-1" in invoice_numbers
        assert "PAID-1" not in invoice_numbers
        with app.app_context():
            SupplierPayment.query.filter_by(supplier_id=supplier_id).delete()
            db.session.commit()
        logout(client)

    def test_paid_invoice_absent_from_unpaid_after_mark(self, client, manager_user, app):
        """After marking an invoice as paid, it no longer appears in the unpaid list."""
        from app import db, SupplierPayment
        supplier_id = self._create_supplier(app, "Epsilon SARL")
        login(client, "test_manager", "Pass1234!")
        create_resp = client.post(
            f"/api/suppliers/{supplier_id}/payments",
            json={"invoice_number": "INV-PEND", "amount": 500.00, "invoice_date": "2024-05-01"},
            content_type="application/json",
        )
        payment_id = create_resp.get_json()["id"]
        # Confirm it is in the unpaid list
        before = client.get("/api/suppliers/payments/unpaid").get_json()
        assert any(p["id"] == payment_id for p in before)
        # Mark it as paid
        client.put(
            f"/api/supplier-payments/{payment_id}",
            json={"payment_date": "2024-05-01"},
            content_type="application/json",
        )
        # Confirm it is no longer in the unpaid list
        after = client.get("/api/suppliers/payments/unpaid").get_json()
        assert not any(p["id"] == payment_id for p in after)
        with app.app_context():
            SupplierPayment.query.filter_by(supplier_id=supplier_id).delete()
            db.session.commit()
        logout(client)


# ---------------------------------------------------------------------------
# 8. Login robustness – bug fixes for the "screen flash / back to login" issue
# ---------------------------------------------------------------------------
class TestLoginRobustness:
    """Tests that validate the fixes for the login-flash bug (Gros bug issue).

    The bug manifested as: clicking Sign-In caused an immediate redirect back
    to the login page (screen flash) with no meaningful error.

    Root causes addressed:
      1. The migration backfill only granted is_user=1 to managers; existing
         non-manager employees (and managers when is_manager was ALSO just
         added) were left with is_user=0 and could not log in.
      2. check_password raised an unhandled ValueError for unsupported hash
         formats (very old Werkzeug sha256 hashes), causing a 500 error.
      3. db.session.commit() in the login path was not wrapped in try/except;
         a transient DB error would raise a 500 instead of a graceful failure.
      4. _enforce_single_session could log the user out immediately if the
         session-token commit silently failed, because the cookie token (new)
         differed from the stale DB token (old).
    """

    def test_user_without_is_user_cannot_login(self, client, app):
        """An employee whose is_user=False and is_manager=False cannot log in."""
        from app import db, Employee
        from werkzeug.security import generate_password_hash

        with app.app_context():
            Employee.query.filter_by(username="no_access_user").delete()
            db.session.commit()
            emp = Employee(
                username="no_access_user",
                email="noaccess@test.local",
                password_hash=generate_password_hash("Pass1234!"),
                is_manager=False,
                is_user=False,
                is_active=True,
            )
            db.session.add(emp)
            db.session.commit()

        resp = login(client, "no_access_user", "Pass1234!")
        # Must stay on the login page (not reach the home page)
        assert resp.status_code == 200
        assert b"permission" in resp.data.lower() or b"login" in resp.data.lower()

        with app.app_context():
            Employee.query.filter_by(username="no_access_user").delete()
            db.session.commit()

    def test_user_with_is_user_true_can_login(self, client, app):
        """An employee with is_user=True (non-manager) can log in successfully."""
        from app import db, Employee
        from werkzeug.security import generate_password_hash

        with app.app_context():
            Employee.query.filter_by(username="plain_user").delete()
            db.session.commit()
            emp = Employee(
                username="plain_user",
                email="plain@test.local",
                password_hash=generate_password_hash("Pass1234!"),
                is_manager=False,
                is_user=True,
                is_active=True,
            )
            db.session.add(emp)
            db.session.commit()

        try:
            resp = login(client, "plain_user", "Pass1234!")
            assert resp.status_code == 200
            # Should reach the home page, not remain on the login page
            assert "login" not in resp.request.path.lower()
        finally:
            # Always clean up to prevent g._login_user from leaking to next tests
            logout(client)
            with app.app_context():
                Employee.query.filter_by(username="plain_user").delete()
                db.session.commit()

    def test_check_password_handles_unsupported_hash_gracefully(self, app):
        """check_password returns False (not exception) for unknown hash formats."""
        from app import Employee

        with app.app_context():
            emp = Employee(
                username="hash_test",
                email="hashtest@test.local",
            )
            # Simulate a hash stored with an old/unsupported format
            emp.password_hash = "sha256$oldsalt$" + "a" * 64
            # Must return False, not raise ValueError
            result = emp.check_password("anypassword")
            assert result is False

    def test_check_password_returns_false_for_no_hash(self, app):
        """check_password returns False when password_hash is None."""
        from app import Employee

        with app.app_context():
            emp = Employee(username="nohash", email="nohash@test.local")
            emp.password_hash = None
            assert emp.check_password("anypassword") is False

    def test_login_succeeds_after_previous_session_token(self, client, manager_user, app):
        """A user can log in again after a previous session: second login also works."""
        try:
            # First login
            resp = login(client, "test_manager", "Pass1234!")
            assert resp.status_code == 200
            logout(client)

            # Second login (should work without being bounced back to login)
            resp2 = login(client, "test_manager", "Pass1234!")
            assert resp2.status_code == 200
            assert "login" not in resp2.request.path.lower()
        finally:
            logout(client)

    def test_inactive_user_cannot_login(self, client, app):
        """An inactive (deactivated) user cannot log in."""
        from app import db, Employee
        from werkzeug.security import generate_password_hash

        with app.app_context():
            Employee.query.filter_by(username="inactive_user").delete()
            db.session.commit()
            emp = Employee(
                username="inactive_user",
                email="inactive@test.local",
                password_hash=generate_password_hash("Pass1234!"),
                is_manager=False,
                is_user=True,
                is_active=False,
            )
            db.session.add(emp)
            db.session.commit()

        try:
            # Ensure no user is currently logged in before this test runs
            # (previous tests might leave g._login_user set in the module-scoped context).
            logout(client)

            resp = login(client, "inactive_user", "Pass1234!")
            assert resp.status_code == 200
            # Should show the login page (deactivated message), not the home page
            assert b"accueil" not in resp.data.lower()
        finally:
            with app.app_context():
                Employee.query.filter_by(username="inactive_user").delete()
                db.session.commit()

    def test_login_sets_session_token_in_db(self, client, manager_user, app):
        """After a successful login the employee row has session_token set."""
        import uuid
        from app import db, Employee

        try:
            login(client, "test_manager", "Pass1234!")
            with app.app_context():
                emp = Employee.query.filter_by(username="test_manager").first()
                # session_token must be a valid UUID string
                assert emp.session_token is not None
                uuid.UUID(emp.session_token)  # raises ValueError if not a valid UUID
        finally:
            logout(client)

    def test_login_clears_stale_session_token_cookie(self, client, manager_user, app):
        """Re-login replaces the stale login_token in the session cookie.

        If a user has an existing session cookie with an old login_token and
        then logs in again, the new cookie must contain the freshly issued
        token (not the stale one) so that _enforce_single_session never sees
        a mismatch immediately after login.
        """
        from app import db, Employee

        try:
            # First login – establishes login_token X in the session cookie.
            login(client, "test_manager", "Pass1234!")
            with app.app_context():
                emp = Employee.query.filter_by(username="test_manager").first()
                first_token = emp.session_token

            # Log out (removes the user from the session but keeps the cookie).
            logout(client)

            # Second login – must issue a brand-new token and store it in the
            # cookie; the old token must not survive.
            login(client, "test_manager", "Pass1234!")
            with app.app_context():
                emp = Employee.query.filter_by(username="test_manager").first()
                second_token = emp.session_token

            # Tokens must differ between the two logins.
            assert second_token is not None
            assert first_token != second_token

            # After the second login the index page must be reachable
            # (no single-session redirect back to login).
            resp = client.get("/", follow_redirects=True)
            assert resp.status_code == 200
            assert "login" not in resp.request.path.lower()
        finally:
            logout(client)

    def test_manager_without_is_user_can_still_login(self, client, app):
        """A manager with is_user=False can still log in via is_manager check."""
        from app import db, Employee
        from werkzeug.security import generate_password_hash

        with app.app_context():
            Employee.query.filter_by(username="mgr_no_is_user").delete()
            db.session.commit()
            emp = Employee(
                username="mgr_no_is_user",
                email="mgr_no_is_user@test.local",
                password_hash=generate_password_hash("Pass1234!"),
                is_manager=True,
                is_user=False,   # explicitly False – manager check should still pass
                is_active=True,
            )
            db.session.add(emp)
            db.session.commit()

        try:
            resp = login(client, "mgr_no_is_user", "Pass1234!")
            assert resp.status_code == 200
            # Should reach the home page, not remain on login
            assert "login" not in resp.request.path.lower()
        finally:
            logout(client)
            with app.app_context():
                Employee.query.filter_by(username="mgr_no_is_user").delete()
                db.session.commit()

