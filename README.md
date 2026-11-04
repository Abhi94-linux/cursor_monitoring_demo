# Server Monitor

Local demo so internal teams can read Linux server health from one browser on this machine.

## CI on GitHub

A green Actions run is the check before starting the demo locally. The workflow has one test job: it checks out the repo, installs `requirements.txt`, and runs the unit tests. It uses no credentials, does not print environment values, and does not upload `.env` or `data/`. It does not publish a package or open a session to a server. GitHub Actions does not reach real servers.

## Run on this computer

The app is started only on this machine, bound to `127.0.0.1` port `5000`.

From the project directory:

1. Create a virtual environment: `python3 -m venv .venv`
2. Activate it: `source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy the example env file: `cp .env.example .env`
5. Set `SECRET_KEY` in `.env` to a long random string:

   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

6. Generate `ADMIN_PASSWORD_HASH` with Werkzeug and paste the hash into `.env`. The sign-in name is `admin`.

   ```bash
   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))"
   ```

7. Start the app: `python app.py`
8. Open [http://127.0.0.1:5000](http://127.0.0.1:5000), sign in, and add a Linux host that accepts the SSH user and password from the form.

The app will not start until both `SECRET_KEY` and `ADMIN_PASSWORD_HASH` are set.

There is no password-change screen. Replacing the hash means editing `.env` and restarting the app.

The target account only needs permission to read proc files and run `df` and `ps`. It does not need root. The host key must already be in the operator’s `known_hosts`. An unknown key is rejected.

## Sign in

The sign-in page asks for a username and password. Only `admin` with the password that matches `ADMIN_PASSWORD_HASH` opens a session. A wrong username and a wrong password show the same error.

After sign-in, the header shows **Sign out**. Sign out clears the session only. It does not change the stored hash.

These screens require a session:

- Server list at `/`
- Add server at `/servers/add`
- Server detail at `/servers/<id>`

The sign-in page does not.

## Server list

Each row shows the display name, host, status, CPU percent, memory percent, and the fullest disk. The name links to that server’s detail page. The page reads the latest sample already in memory. It does not open SSH itself.

Status labels are `pending`, `online`, and `offline`. A server with no sample yet is pending. A failed poll is offline and shows the short error from that poll. The poller runs every 15 seconds. Each server has an 8 second timeout, and one slow host does not stop the others.

`data/servers.json` holds the SSH passwords for this local demo. The file is mode `0600`, it is gitignored, and it must stay on this machine. Restarting the app keeps this file and drops chart data. History lives in process memory for 30 minutes and is cleared on restart.

## Add a server

The form has five fields:

| Field | Rule |
| --- | --- |
| Display name | Required |
| Host | Required hostname or IP |
| SSH port | Required, default `22` |
| SSH username | Required |
| SSH password | Required, stored only in `data/servers.json` |

Each row has **Remove**, which deletes that server from the list and from `data/servers.json`. There is no edit control and no way to type a command.

## Metrics

The browser cannot replace these commands. The collector runs only this fixed list. `127.0.0.1`, `localhost`, and `::1` are read on this machine with those same commands. The SSH password is not used for that host.

| Metric | Read from | Command |
| --- | --- | --- |
| CPU percent | Two reads of `/proc/stat`, compared between polls | `cat /proc/stat` |
| Load average | `/proc/loadavg` | `cat /proc/loadavg` |
| Memory and swap | `/proc/meminfo` | `cat /proc/meminfo` |
| Disk | `df -P` | `df -P` |
| Network throughput | Two reads of `/proc/net/dev`, compared between polls | `cat /proc/net/dev` |
| Processes | `ps` output, ranked in the app | `ps -eo user=,pid=,pcpu=,pmem=,args=` |

The first poll has no CPU or network rate yet. Those values show “waiting for next sample” until the second poll.

## Server detail

The detail page follows the same order as the requirements:

1. Summary — name, host, port, status, last successful poll, last error if any
2. CPU — current percent, 1, 5, and 15 minute load, and a CPU percent chart
3. Memory — total, used, free, and swap, and a used-memory percent chart
4. Disk — one row per mount: size, used, available, use percent
5. Network — one row per interface for current in and out, and a chart of total in and total out
6. Processes — top 10 by CPU and top 10 by memory

The three charts are CPU percent, used memory percent, and total network in/out. They use the in-memory samples for that server, up to 30 minutes. A link goes back to the list. The page has no button that changes the host.

## Layout

- Header with “Server monitoring”, “Local demo”, and **Sign out** while the session is active
- One stylesheet, `static/style.css`
- No theme switch

Jinja autoescape stays on. Chart.js is loaded only on the detail page, from `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js` with a subresource integrity hash.

## Tests

```bash
python -m unittest discover -s tests
```
