"""Server list on disk, metric samples in memory."""

import copy
import json
import os
import threading
import time
import uuid
from pathlib import Path

HISTORY_SECONDS = 30 * 60


def demo_server_path(root):
    """Resolve data/servers.json and refuse a path that leaves data/."""
    data = (Path(root) / "data").resolve()
    path = (data / "servers.json").resolve()
    if path.parent != data:
        raise ValueError("server list must stay inside data/")
    return path


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.servers = []
        self.metrics = {}
        self.load()

    def load(self):
        if not self.path.exists():
            self.servers = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{self.path} is not valid JSON") from exc
        if not isinstance(data, list):
            raise SystemExit(f"{self.path} must contain a list")
        required = ("id", "name", "host", "port", "username", "password")
        for item in data:
            if not isinstance(item, dict) or any(key not in item for key in required):
                raise SystemExit(f"{self.path} is missing server fields")
        self.servers = data

    def add(self, name, host, port, username, password):
        server = {
            "id": uuid.uuid4().hex,
            "name": name,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
        }
        with self.lock:
            self.servers.append(server)
            self._write()
            self.metrics[server["id"]] = _empty_state()
        return copy.deepcopy(server)

    def remove(self, server_id):
        with self.lock:
            kept = [item for item in self.servers if item["id"] != server_id]
            if len(kept) == len(self.servers):
                return False
            self.servers = kept
            self.metrics.pop(server_id, None)
            self._write()
            return True

    def servers_for_poll(self):
        with self.lock:
            return copy.deepcopy(self.servers)

    def baseline(self, server_id):
        with self.lock:
            state = self.metrics.get(server_id)
            if not state or state["baseline"] is None:
                return None
            return copy.deepcopy(state["baseline"])

    def mark_online(self, server_id, sample, baseline):
        with self.lock:
            state = self.metrics.setdefault(server_id, _empty_state())
            state["samples"].append(sample)
            _prune(state, sample["ts"])
            state["baseline"] = baseline
            state["status"] = "online"
            state["last_error"] = None
            state["last_success"] = sample["ts"]

    def mark_offline(self, server_id, message):
        with self.lock:
            state = self.metrics.setdefault(server_id, _empty_state())
            state["status"] = "offline"
            state["last_error"] = message

    def rows(self):
        with self.lock:
            rows = []
            for server in self.servers:
                state = self.metrics.get(server["id"]) or _empty_state()
                _prune(state, time.time())
                latest = state["samples"][-1] if state["samples"] else None
                rows.append(
                    {
                        "id": server["id"],
                        "name": server["name"],
                        "host": server["host"],
                        "port": server["port"],
                        "status": state["status"],
                        "last_error": state["last_error"],
                        "latest": copy.deepcopy(latest),
                    }
                )
            return rows

    def detail(self, server_id):
        with self.lock:
            server = next((item for item in self.servers if item["id"] == server_id), None)
            if server is None:
                return None
            state = self.metrics.get(server_id) or _empty_state()
            now = time.time()
            _prune(state, now)
            return {
                "id": server["id"],
                "name": server["name"],
                "host": server["host"],
                "port": server["port"],
                "status": state["status"],
                "last_error": state["last_error"],
                "last_success": state["last_success"],
                "latest": copy.deepcopy(state["samples"][-1] if state["samples"] else None),
                "samples": copy.deepcopy(state["samples"]),
            }

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.servers, indent=2)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)


def _empty_state():
    return {
        "status": "pending",
        "last_error": None,
        "last_success": None,
        "samples": [],
        "baseline": None,
    }


def _prune(state, now):
    cutoff = now - HISTORY_SECONDS
    state["samples"] = [sample for sample in state["samples"] if sample["ts"] >= cutoff]


def fullest_disk(disks):
    if not disks:
        return None
    return max(disks, key=lambda disk: (disk["percent"], disk["mount"]))
