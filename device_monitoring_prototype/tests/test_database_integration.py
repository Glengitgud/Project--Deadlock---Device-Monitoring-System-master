import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash

from device_monitoring_prototype.python.app import create_app
from device_monitoring_prototype.python.models import (
    Device,
    DiagnosticRun,
    NetworkRecord,
    Role,
    User,
    db,
)


class DatabaseIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "integration-test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Role(name="Administrator"),
                    Role(name="User"),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def register_and_login(self):
        self.client.get("/register")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "full_name": "Test User",
                "email": "test@example.com",
                "username": "testuser",
                "password": "correct-horse-battery-staple",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = User.query.filter_by(username="testuser").one()
            self.assertTrue(
                check_password_hash(user.password_hash, "correct-horse-battery-staple")
            )
            self.assertNotEqual(user.password_hash, "correct-horse-battery-staple")

        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "testuser",
                "password": "incorrect-password",
            },
        )
        self.assertEqual(response.status_code, 401)
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "testuser",
                "password": "correct-horse-battery-staple",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.get("/dashboard")
        with self.client.session_transaction() as session:
            return session["_csrf_token"]

    def test_registration_login_and_password_hash(self):
        self.register_and_login()
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_device_registration_and_history_are_persisted(self):
        token = self.register_and_login()
        hardware = {
            "cpu_model": "Test CPU",
            "cpu_cores": 4,
            "cpu_threads": 8,
            "memory_bytes": 16 * 1024**3,
            "storage_bytes": 512 * 1024**3,
            "gpu_model": None,
            "motherboard_model": None,
            "operating_system_version": "Test OS",
        }
        network = {
            "ip_address": "192.0.2.10",
            "subnet_mask": "255.255.255.0",
            "default_gateway": "192.0.2.1",
            "dns_server": "192.0.2.53",
            "connectivity_status": "connected",
        }
        with patch(
            "device_monitoring_prototype.python.services.collect_hardware",
            return_value=hardware,
        ), patch(
            "device_monitoring_prototype.python.services.collect_network",
            return_value=network,
        ):
            response = self.client.post(
                "/api/devices",
                headers={"X-CSRF-Token": token},
                json={
                    "name": "Test Laptop",
                    "hostname": "test-laptop",
                    "type": "Laptop",
                    "os": "Test OS",
                    "status": "online",
                },
            )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        device_id = response.json["id"]
        with self.app.app_context():
            device = db.session.get(Device, device_id)
            self.assertEqual(device.owner.username, "testuser")
            self.assertEqual(device.hardware_spec.cpu_model, "Test CPU")
            self.assertEqual(len(device.network_records), 1)

        response = self.client.post(
            f"/api/devices/{device_id}/diagnostics",
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201)
        history = self.client.get(f"/api/devices/{device_id}/history")
        self.assertEqual(len(history.json["diagnostics"]), 1)
        self.assertEqual(len(history.json["network"]), 1)
        with self.app.app_context():
            self.assertEqual(DiagnosticRun.query.count(), 1)
            self.assertEqual(NetworkRecord.query.count(), 1)

    def test_standard_user_cannot_open_admin_panel(self):
        self.register_and_login()
        self.assertEqual(self.client.get("/admin").status_code, 403)

    def test_admin_can_create_users_and_role_changes_are_server_checked(self):
        with self.app.app_context():
            administrator = User(
                username="rootadmin",
                email="admin@example.com",
                full_name="Root Admin",
                password_hash=generate_password_hash("admin-password-long-enough"),
                status="active",
            )
            administrator.roles.append(Role.query.filter_by(name="Administrator").one())
            db.session.add(administrator)
            db.session.commit()
            admin_id = administrator.id

        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "rootadmin",
                "password": "admin-password-long-enough",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 200)
        self.client.get("/dashboard")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]

        response = self.client.post(
            "/api/users",
            headers={"X-CSRF-Token": token},
            json={
                "full_name": "Managed User",
                "email": "managed@example.com",
                "username": "managed",
                "password": "managed-password-long-enough",
                "role": "User",
            },
        )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        denied = self.client.patch(
            f"/api/users/{admin_id}",
            headers={"X-CSRF-Token": token},
            json={"role": "User"},
        )
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(self.client.get("/api/users").status_code, 200)

    def test_account_lockout_after_five_failed_attempts(self):
        token = self.register_and_login()
        # Logout
        self.client.post("/logout", data={"csrf_token": token})

        # Submit 5 incorrect passwords
        self.client.get("/login")
        with self.client.session_transaction() as session:
            login_token = session["_csrf_token"]

        for i in range(5):
            res = self.client.post(
                "/login",
                data={
                    "csrf_token": login_token,
                    "username": "testuser",
                    "password": "wrong-password",
                },
            )
            self.assertEqual(res.status_code, 401)

        with self.app.app_context():
            user = User.query.filter_by(username="testuser").one()
            self.assertEqual(user.status, "locked")
            self.assertEqual(user.failed_login_attempts, 5)

        # Even with correct password, locked user is denied
        res = self.client.post(
            "/login",
            data={
                "csrf_token": login_token,
                "username": "testuser",
                "password": "correct-horse-battery-staple",
            },
        )
        self.assertEqual(res.status_code, 401)
        self.assertIn("Account is locked", res.get_data(as_text=True))

    def test_password_recovery_and_reset_flow(self):
        token = self.register_and_login()
        # Logout first so user is unauthenticated
        self.client.post("/logout", data={"csrf_token": token})

        self.client.get("/forgot-password")
        with self.client.session_transaction() as session:
            csrf = session["_csrf_token"]

        from device_monitoring_prototype.python.security import generate_reset_token

        reset_token = generate_reset_token("test@example.com", "integration-test-secret")
        reset_res = self.client.post(
            f"/reset-password/{reset_token}",
            data={
                "csrf_token": csrf,
                "new_password": "brand-new-super-secure-password-123",
                "confirm_password": "brand-new-super-secure-password-123",
            },
        )
        self.assertEqual(reset_res.status_code, 302)

        # Login with new password
        login_res = self.client.post(
            "/login",
            data={
                "csrf_token": csrf,
                "username": "testuser",
                "password": "brand-new-super-secure-password-123",
            },
        )
        self.assertEqual(login_res.status_code, 302)

    def test_endpoint_agent_registration_and_telemetry_flow(self):
        self.register_and_login()
        # Register remote agent device
        reg_resp = self.client.post(
            "/api/agent/register",
            json={
                "username": "testuser",
                "password": "correct-horse-battery-staple",
                "name": "Remote-Worker-PC",
                "hostname": "remote-pc-01",
                "type": "Laptop",
                "os": "Ubuntu 24.04",
            },
        )
        self.assertEqual(reg_resp.status_code, 201)
        data = reg_resp.json
        device_id = data["device_id"]
        token = data["token"]
        self.assertTrue(token)

        # Ingest metrics
        metric_resp = self.client.post(
            "/api/agent/metrics",
            headers={"X-Device-Token": token},
            json={
                "cpu_percent": 92.5,
                "memory_percent": 75.0,
                "storage_percent": 60.0,
                "memory_used_bytes": 12 * 1024**3,
                "storage_used_bytes": 300 * 1024**3,
                "network_rx_bytes": 1000000,
                "network_tx_bytes": 500000,
            },
        )
        self.assertEqual(metric_resp.status_code, 200)

        # Check alert was triggered for high CPU (> 85%)
        alerts_resp = self.client.get("/api/alerts")
        self.assertEqual(alerts_resp.status_code, 200)
        alerts = alerts_resp.json
        self.assertTrue(any("High CPU utilization" in a["title"] for a in alerts))

        # Check CSV export
        csv_resp = self.client.get("/api/reports/devices")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("Remote-Worker-PC", csv_resp.get_data(as_text=True))



if __name__ == "__main__":
    unittest.main()
