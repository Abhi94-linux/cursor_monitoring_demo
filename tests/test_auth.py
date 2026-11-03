"""Sign-in tests. The hash is created here and no real .env file is read."""

import io
import logging
import unittest

from werkzeug.security import generate_password_hash

from app import create_app, require_settings

PASSWORD = "correct-horse-demo-9"
OTHER_PASSWORD = "wrong-horse-demo-4"


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.password_hash = generate_password_hash(PASSWORD)
        self.app = create_app("test-secret-key", self.password_hash)
        self.client = self.app.test_client()
        self.log_stream = io.StringIO()
        self.handler = logging.StreamHandler(self.log_stream)
        logging.getLogger().addHandler(self.handler)
        self.app.logger.addHandler(self.handler)

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)
        self.app.logger.removeHandler(self.handler)

    def test_matching_password(self):
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user"), "admin")
        self.assertNotIn(PASSWORD, self.log_stream.getvalue())
        self.assertNotIn(self.password_hash, self.log_stream.getvalue())

    def test_wrong_password(self):
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": OTHER_PASSWORD},
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Invalid username or password.", response.data)
        self.assertNotIn(OTHER_PASSWORD.encode(), response.data)
        self.assertNotIn(self.password_hash.encode(), response.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user", sess)
        logged = self.log_stream.getvalue()
        self.assertNotIn(OTHER_PASSWORD, logged)
        self.assertNotIn(self.password_hash, logged)

    def test_wrong_username(self):
        wrong_user = self.client.post(
            "/login",
            data={"username": "root", "password": PASSWORD},
        )
        wrong_password = self.client.post(
            "/login",
            data={"username": "admin", "password": OTHER_PASSWORD},
        )
        self.assertEqual(wrong_user.status_code, 401)
        self.assertEqual(wrong_user.data, wrong_password.data)
        self.assertNotIn(b"root", wrong_user.data)
        self.assertNotIn(PASSWORD.encode(), wrong_user.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user", sess)

    def test_missing_hash(self):
        with self.assertRaises(SystemExit):
            require_settings({"SECRET_KEY": "present", "ADMIN_PASSWORD_HASH": ""})
        with self.assertRaises(SystemExit):
            require_settings({"SECRET_KEY": "", "ADMIN_PASSWORD_HASH": "present"})

    def test_sign_out(self):
        stored_hash = self.app.config["ADMIN_PASSWORD_HASH"]
        self.client.post("/login", data={"username": "admin", "password": PASSWORD})
        rejected = self.client.get("/logout")
        self.assertEqual(rejected.status_code, 405)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user"), "admin")

        response = self.client.post("/logout")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/login"))
        with self.client.session_transaction() as sess:
            self.assertNotIn("user", sess)
        self.assertEqual(self.app.config["ADMIN_PASSWORD_HASH"], stored_hash)

        home = self.client.get("/")
        self.assertEqual(home.status_code, 302)
        self.assertTrue(home.headers["Location"].endswith("/login"))


if __name__ == "__main__":
    unittest.main()
