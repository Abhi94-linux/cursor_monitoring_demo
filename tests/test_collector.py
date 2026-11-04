"""Collector tests use a fake Paramiko client. CI stays offline."""

import socket
import unittest

import paramiko

from collector import COMMANDS, CollectError, FakeCollector, collect, ensure_allowed


SECRET = "secret-pass"
FIXTURES = {
    "cat /proc/stat": "cpu  100 0 50 850 0 0 0 0\n",
    "cat /proc/loadavg": "0.10 0.20 0.30 1/10 1\n",
    "cat /proc/meminfo": "MemTotal: 1000 kB\nMemFree: 400 kB\nMemAvailable: 500 kB\n",
    "df -P": "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/root 1000 400 600 40% /\n",
    "cat /proc/net/dev": "eth0: 10 0 0 0 0 0 0 0 4 0 0 0 0 0 0 0\n",
    "ps -eo user=,pid=,pcpu=,pmem=,args=": "root 1 0.5 0.2 init\n",
}


class FakeStd:
    def __init__(self, payload):
        self.payload = payload
        self.channel = self

    def read(self):
        return self.payload

    def recv_exit_status(self):
        return 0


class FakeClient:
    def __init__(self, error=None):
        self.error = error
        self.closed = False
        self.commands = []

    def connect(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        body = FIXTURES[command].encode()
        return None, FakeStd(body), FakeStd(b"")

    def close(self):
        self.closed = True


def server():
    return {
        "id": "a" * 32,
        "host": "db.internal",
        "port": 22,
        "username": "monitor",
        "password": SECRET,
    }


class CollectorTests(unittest.TestCase):
    def test_unknown_command_is_rejected_without_a_connection(self):
        with self.assertRaises(CollectError) as caught:
            ensure_allowed("uname")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual([command for _name, command in COMMANDS if command == "df -P"], ["df -P"])

    def test_local_host_is_read_without_ssh(self):
        sample, _baseline = collect(
            {
                "host": "127.0.0.1",
                "port": 22,
                "username": "monitor",
                "password": SECRET,
            },
            None,
        )
        self.assertGreater(sample["memory"]["total"], 0)
        self.assertTrue(sample["disks"])
        self.assertIsNone(sample["cpu_percent"])
        self.assertNotIn(SECRET, str(sample))

    def test_fake_collector_fills_a_sample(self):
        sample = {"ts": 1, "cpu_percent": 3, "password": "nope"}
        collector = FakeCollector(sample)
        filled, _baseline = collector(server(), None)
        self.assertEqual(filled["cpu_percent"], 3)

    def test_success_timeout_and_auth_failure(self):
        client = FakeClient()
        sample, baseline = collect(server(), None, opener=lambda: client)
        self.assertIsNone(sample["cpu_percent"])
        self.assertEqual(sample["load"], [0.10, 0.20, 0.30])
        self.assertTrue(client.closed)
        self.assertNotIn(SECRET, str(sample))
        self.assertEqual(client.commands, [command for _name, command in COMMANDS])

        timed = FakeClient(error=socket.timeout(f"slow {SECRET}"))
        with self.assertRaises(CollectError) as caught:
            collect(server(), None, opener=lambda: timed)
        self.assertEqual(str(caught.exception), "connection timed out")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertTrue(timed.closed)

        denied = FakeClient(error=paramiko.AuthenticationException(f"bad {SECRET}"))
        with self.assertRaises(CollectError) as caught:
            collect(server(), None, opener=lambda: denied)
        self.assertEqual(str(caught.exception), "authentication failed")
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertTrue(denied.closed)

        leaked = FakeClient(error=OSError(f"banner {SECRET}"))
        with self.assertRaises(CollectError) as caught:
            collect(server(), baseline, opener=lambda: leaked)
        self.assertNotIn(SECRET, str(caught.exception))
