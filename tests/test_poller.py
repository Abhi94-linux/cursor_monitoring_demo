"""Poll loop tests use a fake clock and never start a thread."""

import tempfile
import time
import unittest
from pathlib import Path

from collector import FakeCollector
from poller import poll_loop, poll_server
from store import Store


def sample(cpu=12.0):
    return {
        "ts": time.time(),
        "cpu_percent": cpu,
        "load": [0.1, 0.2, 0.3],
        "memory": {
            "total": 100,
            "used": 40,
            "free": 60,
            "used_percent": 40.0,
            "swap_total": 0,
            "swap_used": 0,
        },
        "disks": [{"mount": "/", "size": 10, "used": 4, "available": 6, "percent": 40}],
        "interfaces": [],
        "net_in_bps": None,
        "net_out_bps": None,
        "processes_cpu": [],
        "processes_mem": [],
    }


class PollerTests(unittest.TestCase):
    def test_one_failure_does_not_drop_the_other_server(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "servers.json")
            first = store.add("ok", "ok.example", 22, "monitor", "secret-a")
            second = store.add("down", "down.example", 22, "monitor", "secret-b")
            collector = FakeCollector(sample(), errors={second["id"]: "connection refused"})
            flags = {"stop": False}

            def pause(_seconds):
                flags["stop"] = True

            poll_loop(
                store,
                collector,
                clock=lambda: 100.0,
                pause=pause,
                should_stop=lambda: flags["stop"],
            )
            rows = {row["host"]: row for row in store.rows()}
            self.assertEqual(rows["ok.example"]["status"], "online")
            self.assertEqual(rows["ok.example"]["latest"]["cpu_percent"], 12.0)
            self.assertEqual(rows["down.example"]["status"], "offline")
            self.assertEqual(rows["down.example"]["last_error"], "connection refused")
            self.assertNotIn("password", rows["ok.example"]["latest"])

    def test_poller_drops_ssh_fields_from_a_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "servers.json")
            server = store.add("ok", "ok.example", 22, "monitor", "secret-a")

            def collector(host, baseline):
                leaked = dict(sample())
                leaked["password"] = host["password"]
                leaked["username"] = host["username"]
                return leaked, {}

            poll_server(store, collector, server)
            latest = store.detail(server["id"])["latest"]
            self.assertNotIn("password", latest)
            self.assertNotIn("username", latest)
            self.assertNotIn("secret-a", str(latest))
