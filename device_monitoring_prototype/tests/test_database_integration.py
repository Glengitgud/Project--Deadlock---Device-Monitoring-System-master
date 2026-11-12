import os
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash

from device_monitoring_prototype.app import _database_uri, create_app
from device_monitoring_prototype.app import app as default_app
from device_monitoring_prototype.models import (
    Device,
    DiagnosticRun,
    Log,
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

    def test_login_and_registration_pages_render(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)

    def test_environment_file_is_loaded_from_application_directory(self):
        with patch("device_monitoring_prototype.app.load_dotenv") as load_dotenv:
            create_app(
                {
                    "TESTING": True,
                    "SQLALCHEMY_DATABASE_URI": "sqlite://",
                }
            )
        load_dotenv.assert_called_once_with(
            dotenv_path=Path(default_app.root_path, ".env")
        )

    def test_database_uri_defaults_to_xampp_mysql(self):
        with patch.dict(os.environ, {}, clear=True):
            url = make_url(_database_uri())
        self.assertEqual(url.drivername, "mysql+pymysql")
        self.assertEqual(url.host, "localhost")
        self.assertEqual(url.port, 3306)
        self.assertEqual(url.database, "devmonitor")
        self.assertEqual(url.username, "root")
        self.assertEqual(url.password, "")

    def test_init_db_command_includes_device_logs(self):
        result = self.app.test_cli_runner().invoke(args=["init-db"])
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            self.assertIn("logs", inspect(db.engine).get_table_names())
            self.assertEqual(Role.query.count(), 2)

    def test_init_db_creates_default_admin_once_and_admin_can_log_in(self):
        runner = self.app.test_cli_runner()
        first_result = runner.invoke(args=["init-db"])
        self.assertEqual(first_result.exit_code, 0, first_result.output)
        second_result = runner.invoke(args=["init-db"])
        self.assertEqual(second_result.exit_code, 0, second_result.output)
        self.assertIn("already exists", second_result.output)

        with self.app.app_context():
            administrator = User.query.filter_by(username="admin").one()
            self.assertTrue(administrator.is_admin)
            self.assertTrue(administrator.is_active)
            self.assertTrue(check_password_hash(administrator.password_hash, "admin123"))
            self.assertEqual(User.query.filter_by(username="admin").count(), 1)

        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/login",
            data={"csrf_token": token, "username": "admin", "password": "admin123"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_all_standard_user_pages_and_apis_render(self):
        self.register_and_login()
        for path in ("/dashboard", "/devices", "/api/dashboard", "/api/devices"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        static_response = self.client.get("/static/css/style.css")
        self.assertEqual(static_response.status_code, 200)
        static_response.close()

    def test_auth_forms_report_database_setup_errors_without_500(self):
        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "database-error-test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )
        client = app.test_client()
        try:
            client.get("/login")
            with client.session_transaction() as session:
                token = session["_csrf_token"]
            login_response = client.post(
                "/login",
                data={
                    "csrf_token": token,
                    "username": "missing",
                    "password": "unused",
                },
            )
            self.assertEqual(login_response.status_code, 503)
            self.assertIn(b"database is unavailable", login_response.data.lower())
            self.assertIn(b"Copy-Item", login_response.data)
            self.assertIn(b"device_monitoring_prototype.app init-db", login_response.data)

            with app.app_context():
                db.create_all()
            register_response = client.post(
                "/register",
                data={
                    "csrf_token": token,
                    "full_name": "Test User",
                    "email": "setup@example.com",
                    "username": "setupuser",
                    "password": "correct-horse-battery-staple",
                },
            )
            self.assertEqual(register_response.status_code, 503)
            self.assertIn(b"init-db", register_response.data)
        finally:
            with app.app_context():
                db.session.remove()
                db.drop_all()

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
            "device_monitoring_prototype.services.collect_hardware",
            return_value=hardware,
        ), patch(
            "device_monitoring_prototype.services.collect_network",
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
            self.assertEqual(len(device.logs), 1)
            self.assertEqual(device.logs[0].event, "Device registered")

        response = self.client.post(
            f"/api/devices/{device_id}/diagnostics",
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201)
        history = self.client.get(f"/api/devices/{device_id}/history")
        self.assertEqual(len(history.json["diagnostics"]), 1)
        self.assertEqual(len(history.json["network"]), 1)
        self.assertEqual(len(history.json["logs"]), 2)
        details = self.client.get(f"/api/devices/{device_id}")
        self.assertEqual(details.status_code, 200, details.get_data(as_text=True))
        self.assertEqual(details.json["device_name"], "Test Laptop")
        self.assertEqual(details.json["hostname"], "test-laptop")
        self.assertEqual(details.json["owner"]["username"], "testuser")
        self.assertEqual(details.json["specification"]["cpu_model"], "Test CPU")
        self.assertEqual(details.json["specification"]["cpu_cores"], 4)
        self.assertEqual(details.json["network_records"][0]["ip_address"], "192.0.2.10")
        self.assertEqual(details.json["diagnostics"][0]["checks"][0]["check_name"], "Prototype scan")
        self.assertEqual(len(details.json["logs"]), 2)
        with self.app.app_context():
            self.assertEqual(DiagnosticRun.query.count(), 1)
            self.assertEqual(NetworkRecord.query.count(), 1)
            self.assertEqual(Log.query.count(), 2)

    def test_sample_data_command_creates_linked_records(self):
        result = self.app.test_cli_runner().invoke(
            args=["seed-sample-data"],
            input="sample-password-long\nsample-password-long\n",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        with self.app.app_context():
            user = User.query.filter_by(username="sample_user").one()
            device = Device.query.filter_by(device_name="Sample Laptop").one()
            self.assertEqual(device.owner.id, user.id)
            self.assertEqual(len(device.network_records), 1)
            self.assertEqual(len(device.logs), 1)
            self.assertNotEqual(
                user.password_hash,
                "sample-password-long",
            )

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
