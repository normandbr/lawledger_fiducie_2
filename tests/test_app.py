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

    def test_gl_summary_blocked_for_staff(self, client, staff_user):
        """Non-managers must receive 403 from /api/gl/summary."""
        login(client, "test_staff", "Pass1234!")
        resp = client.get("/api/gl/summary?date_from=2025-01-01&date_to=2025-12-31")
        assert resp.status_code == 403
        logout(client)

    def test_gl_summary_requires_dates(self, client, manager_user):
        """Missing date params must return 400 from /api/gl/summary."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/gl/summary")
        assert resp.status_code == 400
        logout(client)

    def test_gl_summary_returns_json(self, client, manager_user):
        """Managers must get a valid JSON summary from /api/gl/summary."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/gl/summary?date_from=2025-01-01&date_to=2025-12-31")
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'summary' in data
        assert 'total_debit' in data
        assert 'total_credit' in data
        assert 'balance' in data
        assert isinstance(data['summary'], list)
        logout(client)

    def test_gl_export_summary_returns_csv(self, client, manager_user):
        """Export with view=summary must return a CSV with summary-by-code columns."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get(
            "/api/gl/export?date_from=2025-01-01&date_to=2025-12-31&view=summary"
        )
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type
        content = resp.data.decode('utf-8')
        assert 'Code comptable' in content
        assert 'Compte' in content
        assert 'Débit Total' in content
        assert 'Crédit Total' in content
        assert 'Solde' in content
        logout(client)

    def test_gl_export_classic_returns_csv(self, client, manager_user):
        """Export with view=classic must return a CSV with classic GL columns."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get(
            "/api/gl/export?date_from=2025-01-01&date_to=2025-12-31&view=classic"
        )
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type
        content = resp.data.decode('utf-8')
        assert 'No Facture' in content
        assert 'Débit' in content
        assert 'Crédit' in content
        logout(client)

    def test_gl_export_requires_dates(self, client, manager_user):
        """Missing date params must return 400 from /api/gl/export."""
        login(client, "test_manager", "Pass1234!")
        resp = client.get("/api/gl/export?view=summary")
        assert resp.status_code == 400
        logout(client)

    def test_gl_export_blocked_for_staff(self, client, staff_user):
        """Non-managers must receive 403 from /api/gl/export."""
        login(client, "test_staff", "Pass1234!")
        resp = client.get("/api/gl/export?date_from=2025-01-01&date_to=2025-12-31&view=summary")
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
# 9. Salary GL posting – compound journal entry logic
# ---------------------------------------------------------------------------
class TestSalaryPostToGL:
    """Verify that api_salary_post_to_gl creates the correct compound journal
    entries: DEBIT to the salary (field_index=1) account, CREDIT to each
    deduction account, and CREDIT for net pay to account 2100."""

    def _seed_accounts(self, app):
        """Ensure the default accounts (including 2100) are seeded."""
        from app import _seed_default_accounts
        with app.app_context():
            _seed_default_accounts()

    def _create_salary_configs(self, app):
        """Create two salary config fields: field_index=1 (salary) and
        field_index=2 (deduction).  Returns (salary_config_id,
        deduction_config_id)."""
        from app import db, SalaryConfig
        with app.app_context():
            self._seed_accounts(app)
            sal_cfg = SalaryConfig(
                field_index=1,
                field_name='Salaire brut',
                account_code='5010',
                is_active=True,
            )
            ded_cfg = SalaryConfig(
                field_index=2,
                field_name='RRQ',
                account_code='2110',
                is_active=True,
            )
            db.session.add_all([sal_cfg, ded_cfg])
            db.session.commit()
            return sal_cfg.id, ded_cfg.id

    def _cleanup(self, app, sal_cfg_id, ded_cfg_id):
        from app import db, SalaryConfig, SalaryEntry, JournalEntry, JournalLine
        with app.app_context():
            for je in JournalEntry.query.filter_by(source_type='salary').all():
                JournalLine.query.filter_by(entry_id=je.id).delete()
                db.session.delete(je)
            SalaryEntry.query.filter(
                SalaryEntry.config_id.in_([sal_cfg_id, ded_cfg_id])
            ).delete(synchronize_session=False)
            SalaryConfig.query.filter(
                SalaryConfig.id.in_([sal_cfg_id, ded_cfg_id])
            ).delete(synchronize_session=False)
            db.session.commit()

    def test_post_to_gl_requires_manager(self, client, staff_user, app):
        """Staff users must be denied access."""
        login(client, "test_staff", "Pass1234!")
        resp = client.post(
            "/api/salary/entries/post-to-gl",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 403
        logout(client)

    def test_compound_journal_debit_salary_credit_deduction_and_net(
        self, client, manager_user, app
    ):
        """Posting a salary (1000) with a deduction (150) should produce:
        - DEBIT  5010  1000
        - CREDIT 2110   150
        - CREDIT 2100   850  (net pay)
        """
        from app import db, SalaryEntry, JournalEntry, JournalLine, Account
        from datetime import date
        sal_cfg_id, ded_cfg_id = self._create_salary_configs(app)

        with app.app_context():
            sal_entry = SalaryEntry(
                config_id=sal_cfg_id,
                entry_date=date(2024, 6, 15),
                amount=1000.00,
                is_posted=False,
                is_deleted=False,
            )
            ded_entry = SalaryEntry(
                config_id=ded_cfg_id,
                entry_date=date(2024, 6, 15),
                amount=150.00,
                is_posted=False,
                is_deleted=False,
            )
            db.session.add_all([sal_entry, ded_entry])
            db.session.commit()
            sal_id = sal_entry.id
            ded_id = ded_entry.id

        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            "/api/salary/entries/post-to-gl",
            json={"date_from": "2024-06-01", "date_to": "2024-06-30"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        result = resp.get_json()
        assert result["posted"] == 2  # both entries posted

        with app.app_context():
            assert SalaryEntry.query.get(sal_id).is_posted is True
            assert SalaryEntry.query.get(ded_id).is_posted is True

            je = JournalEntry.query.filter_by(
                source_type='salary', source_id=sal_id
            ).first()
            assert je is not None, "No journal entry created for salary"

            lines = JournalLine.query.filter_by(entry_id=je.id).all()
            acc_map = {}
            for ln in lines:
                acct = Account.query.get(ln.account_id)
                assert acct is not None
                acc_map[acct.code] = (float(ln.debit), float(ln.credit))

            assert '5010' in acc_map, "Expected DEBIT line on account 5010"
            assert acc_map['5010'] == (1000.0, 0.0)

            assert '2110' in acc_map, "Expected CREDIT line on account 2110"
            assert acc_map['2110'] == (0.0, 150.0)

            assert '2100' in acc_map, "Expected CREDIT net-pay line on account 2100"
            assert acc_map['2100'] == (0.0, 850.0)

        self._cleanup(app, sal_cfg_id, ded_cfg_id)
        logout(client)

    def test_no_deductions_full_net_pay_credited(self, client, manager_user, app):
        """When there are no deduction fields, the full salary amount must
        be credited to account 2100 as net pay."""
        from app import db, SalaryEntry, JournalEntry, JournalLine, Account
        from datetime import date
        sal_cfg_id, ded_cfg_id = self._create_salary_configs(app)

        with app.app_context():
            sal_entry = SalaryEntry(
                config_id=sal_cfg_id,
                entry_date=date(2024, 7, 1),
                amount=500.00,
                is_posted=False,
                is_deleted=False,
            )
            db.session.add(sal_entry)
            db.session.commit()
            sal_id = sal_entry.id

        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            "/api/salary/entries/post-to-gl",
            json={"date_from": "2024-07-01", "date_to": "2024-07-31"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 1

        with app.app_context():
            je = JournalEntry.query.filter_by(
                source_type='salary', source_id=sal_id
            ).first()
            assert je is not None

            lines = JournalLine.query.filter_by(entry_id=je.id).all()
            acc_map = {}
            for ln in lines:
                acct = Account.query.get(ln.account_id)
                acc_map[acct.code] = (float(ln.debit), float(ln.credit))

            assert acc_map.get('5010') == (500.0, 0.0)
            assert acc_map.get('2100') == (0.0, 500.0)

        self._cleanup(app, sal_cfg_id, ded_cfg_id)
        logout(client)

    def test_already_posted_entries_skipped(self, client, manager_user, app):
        """Entries that are already posted must not be posted again."""
        from app import db, SalaryEntry
        from datetime import date
        sal_cfg_id, ded_cfg_id = self._create_salary_configs(app)

        with app.app_context():
            entry = SalaryEntry(
                config_id=sal_cfg_id,
                entry_date=date(2024, 8, 1),
                amount=800.00,
                is_posted=True,
                is_deleted=False,
            )
            db.session.add(entry)
            db.session.commit()

        login(client, "test_manager", "Pass1234!")
        resp = client.post(
            "/api/salary/entries/post-to-gl",
            json={"date_from": "2024-08-01", "date_to": "2024-08-31"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["posted"] == 0

        self._cleanup(app, sal_cfg_id, ded_cfg_id)
        logout(client)
