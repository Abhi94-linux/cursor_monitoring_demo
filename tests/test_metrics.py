"""Parser tests. Each case is fixture text and opens no sockets."""

import unittest
from unittest import mock

from collector import (
    MAX_OUTPUT,
    CollectError,
    clip_output,
    ensure_allowed,
    parse_cpu,
    parse_disks,
    parse_load,
    parse_mem,
    parse_net,
    parse_processes,
    sample_from_outputs,
    _cpu_percent,
    _network_rates,
)

CPU_A = "cpu  100 0 50 850 0 0 0 0 0 0\ncpu0 100 0 50 850 0 0 0 0 0 0\n"
CPU_B = "cpu  200 0 100 900 0 0 0 0 0 0\n"
LOAD = "0.15 0.25 0.35 2/100 99\n"
MEM = """MemTotal:        1000000 kB
MemFree:          200000 kB
MemAvailable:     400000 kB
SwapTotal:        100000 kB
SwapFree:          40000 kB
"""
DISK = """Filesystem 1024-blocks Used Available Capacity Mounted on
/dev/root 100000 40000 60000 40% /
tmpfs 1000 100 900 10% /run
"""
NET_A = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1000 1 0 0 0 0 0 0 500 1 0 0 0 0 0 0
  eth0: 2000 1 0 0 0 0 0 0 800 1 0 0 0 0 0 0
"""
NET_B = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1000 1 0 0 0 0 0 0 500 1 0 0 0 0 0 0
  eth0: 3000 1 0 0 0 0 0 0 1800 1 0 0 0 0 0 0
"""


def processes(count=12):
    lines = [f"user {index} {index}.0 {count - index}.0 command-{index}" for index in range(1, count + 1)]
    return "\n".join(lines) + "\n"


def outputs(cpu=CPU_A, net=NET_A, ps=None):
    return {
        "cpu": cpu,
        "load": LOAD,
        "mem": MEM,
        "disk": DISK,
        "net": net,
        "ps": processes() if ps is None else ps,
    }


class MetricTests(unittest.TestCase):
    def test_cpu_percent_from_two_readings(self):
        first = parse_cpu(CPU_A)
        second = parse_cpu(CPU_B)
        self.assertEqual(_cpu_percent(*first, *second), 75.0)

    def test_load_memory_disk_network_and_processes(self):
        self.assertEqual(parse_load(LOAD), (0.15, 0.25, 0.35))
        memory = parse_mem(MEM)
        self.assertEqual(memory["total"], 1000000 * 1024)
        self.assertEqual(memory["used"], 600000 * 1024)
        self.assertEqual(memory["swap_used"], 60000 * 1024)
        disks = parse_disks(DISK)
        self.assertEqual(disks[0]["mount"], "/")
        self.assertEqual(disks[0]["percent"], 40)
        self.assertEqual(disks[0]["size"], 100000 * 1024)
        first_net = parse_net(NET_A)
        second_net = parse_net(NET_B)
        rows, total_in, total_out = _network_rates(first_net, second_net, 2)
        eth = next(row for row in rows if row["name"] == "eth0")
        self.assertEqual(eth["in_bps"], 500)
        self.assertEqual(eth["out_bps"], 500)
        self.assertEqual(total_in, 500)
        self.assertEqual(total_out, 500)
        by_cpu, by_mem = parse_processes(processes())
        self.assertEqual(len(by_cpu), 10)
        self.assertEqual(by_cpu[0]["cpu"], 12.0)
        self.assertEqual(by_mem[0]["mem"], 11.0)
        long_command = "x" * 250
        _by_cpu, by_mem = parse_processes(f"root 1 0.1 0.1 {long_command}\n")
        self.assertEqual(len(by_mem[0]["command"]), 200)

    def test_one_reading_waits_for_the_next_sample(self):
        sample, baseline = sample_from_outputs(outputs(), None, now=100, mono=10)
        self.assertIsNone(sample["cpu_percent"])
        self.assertIsNone(sample["net_in_bps"])
        self.assertIsNone(sample["net_out_bps"])
        self.assertIsNone(sample["interfaces"][0]["in_bps"])
        later, _next = sample_from_outputs(outputs(cpu=CPU_B, net=NET_B), baseline, now=115, mono=25)
        self.assertEqual(later["cpu_percent"], 75.0)
        self.assertEqual(later["net_in_bps"], 1000 / 15)

    def test_parsers_clip_text_and_do_not_open_sockets(self):
        self.assertEqual(len(clip_output("y" * (MAX_OUTPUT + 50))), MAX_OUTPUT)
        huge = dict(outputs(), cpu=("cpu  1 0 0 1 0 0 0 0\n" + ("z" * (MAX_OUTPUT + 20))))
        with mock.patch("socket.socket", side_effect=AssertionError("socket opened")):
            sample, _baseline = sample_from_outputs(huge, None, now=1, mono=1)
        self.assertIsNone(sample["cpu_percent"])
        with self.assertRaises(CollectError):
            with mock.patch("socket.socket", side_effect=AssertionError("socket opened")):
                ensure_allowed("rm -rf /")
