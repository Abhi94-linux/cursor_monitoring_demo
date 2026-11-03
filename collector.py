"""Read-only SSH collection for the local monitoring demo."""

import socket
import time

import paramiko

SSH_BUDGET_SECONDS = 8

COMMANDS = (
    ("cpu", "cat /proc/stat"),
    ("load", "cat /proc/loadavg"),
    ("mem", "cat /proc/meminfo"),
    ("disk", "df -P"),
    ("net", "cat /proc/net/dev"),
    ("ps", "ps -eo user=,pid=,pcpu=,pmem=,args="),
)


class CollectError(Exception):
    """A poll failed with a message safe to show in the UI."""


def collect(server, baseline):
    """Connect to one host and return (sample, baseline).

    CPU percent and network rates need the previous poll's counters.
    Those fields are None on the first successful sample.
    """
    password = server["password"]
    outputs = _read_host(server, password)
    now = time.time()
    mono = time.monotonic()
    idle, total = parse_cpu(outputs["cpu"])
    load1, load5, load15 = parse_load(outputs["load"])
    memory = parse_mem(outputs["mem"])
    disks = parse_disks(outputs["disk"])
    counters = parse_net(outputs["net"])
    by_cpu, by_mem = parse_processes(outputs["ps"])

    cpu_percent = None
    if baseline and baseline.get("cpu"):
        prev_idle, prev_total = baseline["cpu"]
        cpu_percent = _cpu_percent(prev_idle, prev_total, idle, total)

    elapsed = None
    prev_net = None
    if baseline and baseline.get("net") and baseline.get("mono") is not None:
        elapsed = mono - baseline["mono"]
        prev_net = baseline["net"]
    interfaces, net_in, net_out = _network_rates(prev_net, counters, elapsed)

    sample = {
        "ts": now,
        "cpu_percent": cpu_percent,
        "load": [load1, load5, load15],
        "memory": memory,
        "disks": disks,
        "interfaces": interfaces,
        "net_in_bps": net_in,
        "net_out_bps": net_out,
        "processes_cpu": by_cpu,
        "processes_mem": by_mem,
    }
    new_baseline = {"cpu": (idle, total), "net": counters, "mono": mono}
    return sample, new_baseline


def parse_cpu(text):
    """Return (idle, total) jiffies from the aggregate cpu line.

    Guest time is already included in user and nice, so it is not added again.
    """
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        try:
            numbers = [int(part) for part in line.split()[1:]]
        except ValueError as exc:
            raise CollectError("unexpected command output") from exc
        if len(numbers) < 4:
            break
        while len(numbers) < 8:
            numbers.append(0)
        user, nice, system, idle, iowait, irq, softirq, steal = numbers[:8]
        idle_all = idle + iowait
        total = user + nice + system + idle_all + irq + softirq + steal
        return idle_all, total
    raise CollectError("unexpected command output")


def parse_load(text):
    parts = text.split()
    if len(parts) < 3:
        raise CollectError("unexpected command output")
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError as exc:
        raise CollectError("unexpected command output") from exc


def parse_mem(text):
    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        token = rest.strip().split()
        if not token:
            continue
        try:
            values[key] = int(token[0])
        except ValueError as exc:
            raise CollectError("unexpected command output") from exc
    if "MemTotal" not in values or "MemFree" not in values:
        raise CollectError("unexpected command output")
    total_kb = values["MemTotal"]
    available_kb = values.get("MemAvailable", values["MemFree"])
    used_kb = max(0, total_kb - available_kb)
    swap_total_kb = values.get("SwapTotal", 0)
    swap_free_kb = values.get("SwapFree", 0)
    swap_used_kb = max(0, swap_total_kb - swap_free_kb)
    used_percent = (used_kb / total_kb * 100) if total_kb else 0.0
    return {
        "total": total_kb * 1024,
        "used": used_kb * 1024,
        "free": available_kb * 1024,
        "used_percent": used_percent,
        "swap_total": swap_total_kb * 1024,
        "swap_used": swap_used_kb * 1024,
    }


def parse_disks(text):
    rows = []
    for line in text.splitlines():
        match_at = _capacity_index(line)
        if match_at is None:
            continue
        percent, mount, before = match_at
        parts = before.split()
        if len(parts) < 4:
            continue
        try:
            blocks, used, available = (int(parts[-3]), int(parts[-2]), int(parts[-1]))
        except ValueError:
            continue
        rows.append(
            {
                "mount": mount,
                "size": blocks * 1024,
                "used": used * 1024,
                "available": available * 1024,
                "percent": percent,
            }
        )
    if not rows:
        raise CollectError("unexpected command output")
    rows.sort(key=lambda row: row["mount"])
    return rows


def parse_net(text):
    counters = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        name = name.strip()
        if not name or name.lower().startswith("inter") or name.lower().startswith("face"):
            continue
        columns = rest.split()
        if len(columns) < 9:
            continue
        try:
            counters[name] = (int(columns[0]), int(columns[8]))
        except ValueError as exc:
            raise CollectError("unexpected command output") from exc
    if not counters:
        raise CollectError("unexpected command output")
    return counters


def parse_processes(text):
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        if len(parts) == 4:
            parts.append("")
        user, pid, cpu, mem, command = parts
        try:
            rows.append(
                {
                    "user": user,
                    "pid": int(pid),
                    "cpu": float(cpu.replace(",", ".")),
                    "mem": float(mem.replace(",", ".")),
                    "command": command.strip()[:200],
                }
            )
        except ValueError:
            continue
    by_cpu = sorted(rows, key=lambda row: row["cpu"], reverse=True)[:10]
    by_mem = sorted(rows, key=lambda row: row["mem"], reverse=True)[:10]
    return by_cpu, by_mem


def _read_host(server, password):
    deadline = time.monotonic() + SSH_BUDGET_SECONDS
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        remaining = max(0.2, deadline - time.monotonic())
        try:
            client.connect(
                hostname=server["host"],
                port=int(server["port"]),
                username=server["username"],
                password=password,
                timeout=remaining,
                auth_timeout=remaining,
                banner_timeout=remaining,
                look_for_keys=False,
                allow_agent=False,
            )
        except paramiko.AuthenticationException as exc:
            raise CollectError("authentication failed") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise CollectError("connection timed out") from exc
        except ConnectionRefusedError as exc:
            raise CollectError("connection refused") from exc
        except socket.gaierror as exc:
            raise CollectError("host not found") from exc
        except (OSError, paramiko.SSHException) as exc:
            raise CollectError(_connect_message(exc, password)) from exc

        outputs = {}
        for name, command in COMMANDS:
            outputs[name] = _exec(client, command, deadline, password)
        return outputs
    finally:
        client.close()


def _exec(client, command, deadline, password):
    remaining = deadline - time.monotonic()
    if remaining <= 0.2:
        raise CollectError("connection timed out")
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=remaining)
        out = stdout.read()
        err = stderr.read()
        code = stdout.channel.recv_exit_status()
    except (socket.timeout, TimeoutError) as exc:
        raise CollectError("connection timed out") from exc
    except (OSError, paramiko.SSHException) as exc:
        raise CollectError(_safe(str(exc), password)) from exc
    if code != 0:
        detail = err.decode("utf-8", "replace").strip().splitlines()
        message = detail[0] if detail else "command failed"
        raise CollectError(_safe(message, password))
    return out.decode("utf-8", "replace")


def _cpu_percent(prev_idle, prev_total, idle, total):
    total_delta = total - prev_total
    idle_delta = idle - prev_idle
    if total_delta <= 0 or idle_delta < 0:
        return None
    used = (1 - (idle_delta / total_delta)) * 100
    return max(0.0, min(100.0, used))


def _network_rates(previous, current, elapsed):
    names = sorted(current, key=lambda name: (name == "lo", name))
    rows = []
    total_in = 0.0
    total_out = 0.0
    any_rate = False
    for name in names:
        rx, tx = current[name]
        in_bps = None
        out_bps = None
        if previous and name in previous and elapsed and elapsed > 0:
            prev_rx, prev_tx = previous[name]
            if rx >= prev_rx and tx >= prev_tx:
                in_bps = (rx - prev_rx) / elapsed
                out_bps = (tx - prev_tx) / elapsed
                total_in += in_bps
                total_out += out_bps
                any_rate = True
        rows.append({"name": name, "in_bps": in_bps, "out_bps": out_bps})
    if not any_rate:
        return rows, None, None
    return rows, total_in, total_out


def _capacity_index(line):
    stripped = line.rstrip()
    marker = None
    for token in stripped.split():
        if token.endswith("%") and token[:-1].isdigit():
            marker = token
    if marker is None:
        return None
    percent = int(marker[:-1])
    before, _sep, after = stripped.rpartition(marker)
    mount = after.strip()
    if not mount:
        return None
    return percent, mount, before


def _connect_message(exc, password):
    nested = list(getattr(exc, "errors", {}).values())
    kinds = [exc, *nested]
    if any(isinstance(item, ConnectionRefusedError) for item in kinds):
        return "connection refused"
    blob = " ".join(str(item) for item in kinds).lower()
    if "connection refused" in blob or "unable to connect" in blob:
        return "connection refused"
    if "timed out" in blob:
        return "connection timed out"
    if "name or service not known" in blob or "temporary failure in name resolution" in blob:
        return "host not found"
    return _safe(str(exc), password)


def _safe(message, password):
    text = " ".join(message.split())
    if password:
        text = text.replace(password, "******")
    return (text or "connection failed")[:180]
