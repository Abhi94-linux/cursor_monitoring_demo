"""Page tests build their own hash and do not read the developer .env."""

import io
import logging
import re
import tempfile
import time
import unittest
from pathlib import Path

from werkzeug.security import generate_password_hash

from app import create_app
from store import Store

PASSWORD = "correct-horse-demo-9"
SSH_PASSWORD = "ssh-secret-xyz"
HASH = generate_password_hash(PASSWORD)


def make_client(store):
    app = create_app("test-secret-key", HASH, store=store)
    client = app.test_client()
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    logging.getLogger().addHandler(handler)
    app.logger.addHandler(handler)
    return app, client, log_stream, handler


def sign_in(client):
    response = client.post("/login", data={"username": "admin", "password": PASSWORD})
    assert response.status_code == 302


def csrf(client):
    page = client.get("/servers/add")
    match = re.search(br'name="csrf_token" value="([^"]+)"', page.data)
    return match.group(1).decode()


def sample(cpu=None):
    return {
        "ts": time.time(),
        "cpu_percent": cpu,
        "load": [0.2, 0.3, 0.4],
        "memory": {
            "total": 2048,
            "used": 1024,
            "free": 1024,
            "used_percent": 50.0,
            "swap_total": 0,
            "swap_used": 0,
        },
        "disks": [{"mount": "/", "size": 4096, "used": 2048, "available": 2048, "percent": 50}],
        "interfaces": [{"name": "eth0", "in_bps": 100.0, "out_bps": 40.0}],
        "net_in_bps": 100.0,
        "net_out_bps": 40.0,
        "processes_cpu": [
            {"user": "root", "pid": 1, "cpu": 1.0, "mem": 0.4, "command": "init <script>"}
        ],
        "processes_mem": [
            {"user": "root", "pid": 1, "cpu": 1.0, "mem": 0.4, "command": "init <script>"}
        ],
    }


class PageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / "servers.json")
        self.app, self.client, self.logs, self.handler = make_client(self.store)

    def tearDown(self):
        logging.getLogger().removeHandler(self.handler)
        self.app.logger.removeHandler(self.handler)
        self.directory.cleanup()

    def test_signed_out_home_redirects_and_signed_in_list_is_empty(self):
        signed_out = self.client.get("/")
        self.assertEqual(signed_out.status_code, 302)
        self.assertTrue(signed_out.headers["Location"].endswith("/login"))
        sign_in(self.client)
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"No servers yet", page.data)
        self.assertIn(b"Add server", page.data)
        self.assertNotIn(b"Edit", page.data)

    def test_remove_requires_a_session_and_csrf(self):
        server = self.store.add("web", "db.internal", 22, "monitor", SSH_PASSWORD)
        signed_out = self.client.post(f"/servers/{server['id']}/remove")
        self.assertEqual(signed_out.status_code, 302)
        self.assertTrue(signed_out.headers["Location"].endswith("/login"))
        self.assertEqual(len(self.store.servers), 1)

        sign_in(self.client)
        blocked = self.client.post(f"/servers/{server['id']}/remove", data={"csrf_token": "nope"})
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(len(self.store.servers), 1)

        page = self.client.get("/")
        token = re.search(br'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        self.assertIn(b"Remove", page.data)
        removed = self.client.post(
            f"/servers/{server['id']}/remove",
            data={"csrf_token": token},
        )
        self.assertEqual(removed.status_code, 302)
        self.assertEqual(self.store.servers, [])
        self.assertNotIn(SSH_PASSWORD.encode(), removed.data)
        self.assertNotIn(SSH_PASSWORD, self.logs.getvalue())

    def test_add_server_validation_and_secret_logging(self):
        sign_in(self.client)
        token = csrf(self.client)
        missing = self.client.post(
            "/servers/add",
            data={"csrf_token": token, "name": "", "host": "", "port": "22", "username": "", "password": ""},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(self.store.servers, [])

        bad_port = self.client.post(
            "/servers/add",
            data={
                "csrf_token": token,
                "name": "web",
                "host": "db.internal",
                "port": "70000",
                "username": "monitor",
                "password": SSH_PASSWORD,
            },
        )
        self.assertEqual(bad_port.status_code, 400)
        self.assertIn(b"SSH port must be a number from 1 to 65535.", bad_port.data)
        self.assertNotIn(SSH_PASSWORD.encode(), bad_port.data)
        self.assertNotIn(SSH_PASSWORD, self.logs.getvalue())

        saved = self.client.post(
            "/servers/add",
            data={
                "csrf_token": token,
                "name": "web <b>",
                "host": "db.internal",
                "port": "22",
                "username": "monitor",
                "password": SSH_PASSWORD,
            },
        )
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(self.store.servers[0]["password"], SSH_PASSWORD)
        page = self.client.get("/")
        self.assertNotIn(SSH_PASSWORD.encode(), page.data)
        self.assertIn(b"web &lt;b&gt;", page.data)
        self.assertNotIn(SSH_PASSWORD, self.logs.getvalue())

    def test_rows_escape_host_text_for_each_status(self):
        sign_in(self.client)
        pending = self.store.add("web", 'h<ost>&"', 22, "monitor", SSH_PASSWORD)
        online = self.store.add("online", "ok.example", 22, "monitor", SSH_PASSWORD)
        offline = self.store.add("offline", "down.example", 22, "monitor", SSH_PASSWORD)
        self.store.mark_online(online["id"], sample(cpu=15.5), {})
        self.store.mark_offline(offline["id"], "connection refused")
        page = self.client.get("/")
        self.assertIn(b"h&lt;ost&gt;&amp;&#34;", page.data)
        self.assertNotIn(b'h<ost>&"', page.data)
        self.assertIn(b"pending", page.data)
        self.assertIn(b"online", page.data)
        self.assertIn(b"offline", page.data)
        self.assertIn(b"connection refused", page.data)
        self.assertIn(b"15.5%", page.data)
        self.assertNotIn(SSH_PASSWORD.encode(), page.data)
        self.assertIn(pending["id"].encode(), page.data)

    def test_detail_known_unknown_and_waiting(self):
        sign_in(self.client)
        server = self.store.add("web", "db.internal", 22, "monitor", SSH_PASSWORD)
        self.store.mark_online(server["id"], sample(cpu=None), {})
        waiting = self.client.get(f"/servers/{server['id']}")
        self.assertEqual(waiting.status_code, 200)
        self.assertIn(b"Waiting for next sample", waiting.data)
        self.assertIn(b"init &lt;script&gt;", waiting.data)
        self.assertIn(b"100.0", waiting.data)
        self.assertNotIn(b"password", waiting.data.lower())
        self.assertNotIn(SSH_PASSWORD.encode(), waiting.data)

        unknown = self.client.get("/servers/not-a-file-path")
        self.assertEqual(unknown.status_code, 404)
        self.assertFalse((Path(self.directory.name) / "not-a-file-path").exists())
