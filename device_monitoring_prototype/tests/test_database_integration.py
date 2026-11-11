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


if __name__ == "__main__":
    unittest.main()
