"""Server list and in-memory sample tests. Nothing is written under data/."""

import stat
import tempfile
import time
import unittest
from pathlib import Path

from store import HISTORY_SECONDS, Store, demo_server_path


def sample(ts, cpu=10.0):
    return {
        "ts": ts,
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
        "disks": [{"mount": "/", "size": 100, "used": 40, "available": 60, "percent": 40}],
        "interfaces": [{"name": "eth0", "in_bps": 1.0, "out_bps": 2.0}],
        "net_in_bps": 1.0,
        "net_out_bps": 2.0,
        "processes_cpu": [],
        "processes_mem": [],
    }


class StoreTests(unittest.TestCase):
    def test_append_and_reload_uses_a_temp_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "servers.json"
            store = Store(path)
            saved = store.add("web", "db.internal", 22, "monitor", "ssh-secret")
            reloaded = Store(path)
            self.assertEqual(reloaded.servers[0]["host"], "db.internal")
            self.assertEqual(reloaded.servers[0]["password"], "ssh-secret")
            self.assertEqual(reloaded.servers[0]["id"], saved["id"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(reloaded.detail(saved["id"])["samples"], [])
            self.assertTrue(str(path).startswith(directory))
            self.assertFalse(str(path).endswith("data/servers.json"))

    def test_demo_path_stays_inside_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = demo_server_path(directory)
            self.assertEqual(path, Path(directory).resolve() / "data" / "servers.json")

    def test_history_cap_and_empty_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "servers.json")
            server = store.add("web", "db.internal", 22, "monitor", "ssh-secret")
            self.assertEqual(store.detail(server["id"])["samples"], [])
            now = time.time()
            store.mark_online(server["id"], sample(now - HISTORY_SECONDS - 5, cpu=1), {})
            store.mark_online(server["id"], sample(now, cpu=25), {})
            kept = store.detail(server["id"])["samples"]
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0]["cpu_percent"], 25)
            self.assertNotIn("password", kept[0])
            self.assertNotIn("username", kept[0])

    def test_remove_drops_the_server_and_its_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "servers.json"
            store = Store(path)
            first = store.add("web", "db.internal", 22, "monitor", "ssh-secret")
            second = store.add("other", "other.internal", 22, "monitor", "ssh-secret")
            store.mark_online(first["id"], sample(time.time()), {})
            self.assertTrue(store.remove(first["id"]))
            self.assertFalse(store.remove(first["id"]))
            reloaded = Store(path)
            self.assertEqual([item["id"] for item in reloaded.servers], [second["id"]])
            self.assertIsNone(store.detail(first["id"]))
