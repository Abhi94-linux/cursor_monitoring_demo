# Implementation TODO

Work top to bottom. Complete one checkbox before the next. Each step is a small change plus its security check and a short doc update.

The app stays a local demo: Python, Flask, bind `127.0.0.1:5000`. Follow `docs/requirements.md`.

## 1. Project initialization and basic UI

- [x] Add `requirements.txt` (Flask), `app.py`, `templates/base.html`, `static/style.css`, and `.gitignore`.
  - [x] **Security:** Listen on `127.0.0.1` port `5000` only. `.gitignore` covers `.env`, `data/servers.json`, virtualenvs, and `__pycache__`. Commit no secrets.
  - [x] **Docs:** `README.md` with the local steps: create a virtualenv, install dependencies, start the app, open `http://127.0.0.1:5000`.

- [x] Serve one placeholder page from the base layout: app name, short description, readable type, and enough contrast to scan. No server actions yet.
  - [x] **Security:** Jinja autoescape stays on. The page has no form and no external script.
  - [x] **Docs:** README describes the placeholder page and the layout (header, one stylesheet, no theme switch).

## 2. Sign-in and unit tests

- [x] Add `.env.example` with `SECRET_KEY` and `ADMIN_PASSWORD_HASH`. Load both at startup.
  - [x] **Security:** Refuse to start when either value is missing. The example file contains empty placeholders, never a real hash or key.
  - [x] **Docs:** README shows how to copy `.env.example` to `.env`, set `SECRET_KEY`, and generate `ADMIN_PASSWORD_HASH` with Werkzeug. Sign-in name is `admin`.

- [x] Add the sign-in page (username, password, submit), check the password with Werkzeug, and start a session on success.
  - [x] **Security:** Username must be `admin`. Wrong user and wrong password show the same error. Session cookie is HttpOnly and SameSite=Lax. Logs omit the password and the hash.
  - [x] **Docs:** README states there is no password-change screen; replacing the hash means editing `.env` and restarting.

- [x] Add sign-out, which clears the session.
  - [x] **Security:** Sign-out only drops the session cookie. It does not change the stored hash.
  - [x] **Docs:** README notes the sign-out control in the header.

- [x] Add unit tests for a matching password, a wrong password, a wrong username, a missing hash, and sign-out.
  - [x] **Security:** Tests use a hash generated in the test, not a password checked in from a real `.env`.
  - [x] **Docs:** README gives the one command that runs the tests.

## 3. CI/CD with GitHub Actions

- [x] Add `.github/workflows/ci.yml`. On push and pull request: set up Python, install `requirements.txt`, run the unit tests.
  - [x] **Security:** The workflow checks out the repo and runs tests. It uses no credentials, prints no env values, and does not upload `.env` or `data/`.
  - [x] **Docs:** README says a green Actions run is the check before starting the demo locally.

- [x] Keep delivery local. The workflow has a single test job.
  - [x] **Security:** The app is started only on this machine, bound to `127.0.0.1`. The workflow does not publish a package or open a remote session.
  - [x] **Docs:** README separates “CI on GitHub” from “run on this computer” in a few lines.

## 4. Signed-in server list shell

- [x] Send every page except sign-in back to the sign-in page when the session is missing. Point `/` at an empty server table and an “Add server” link.
  - [x] **Security:** The guard is one shared check used by every new route. The table has no edit, delete, or command control.
  - [x] **Docs:** README lists the screens that require a session.

- [x] Test that a signed-out request to `/` redirects to sign-in, and a signed-in request sees the empty list.
  - [x] **Security:** The test client does not load the developer `.env`.
  - [x] **Docs:** Leave the test command in the README unchanged so CI picks up the new tests.

## 5. Save the server list

- [x] Add a helper that reads and appends `data/servers.json` (id, display name, host, port, SSH username, SSH password).
  - [x] **Security:** Create the file with mode `0600`. Keep SSH passwords only in that file. Resolve the path inside the project `data/` directory. Leave the file gitignored.
  - [x] **Docs:** README says the file holds SSH passwords for this local demo and must stay on this machine.

- [x] Unit-test append and reload with a temp file.
  - [x] **Security:** Tests write under a temp directory, not the real `data/servers.json`.
  - [x] **Docs:** Note in the README that restarting the app keeps this file and drops chart data (charts come later).

## 6. Add-server form

- [x] Add the form: display name, host, SSH port (default 22), SSH username, SSH password. Save and return to the list.
  - [x] **Security:** Require a signed-in session and a CSRF token. Validate on the server: all fields present, port 1–65535. Store the SSH password only in `data/servers.json`. The page offers no edit or delete.
  - [x] **Docs:** README lists the five fields and the default port.

- [x] Unit-test missing fields, a bad port, and a successful append.
  - [x] **Security:** Assertions check the password is absent from the response body and from log output captured in the test.
  - [x] **Docs:** No README change beyond the test command already documented.

## 7. In-memory samples

- [x] Add a store that keeps one server’s samples for 30 minutes (about 120 points at a 15 second poll).
  - [x] **Security:** A sample holds metrics only. It does not hold the SSH password or username.
  - [x] **Docs:** README states history lives in process memory for 30 minutes and is cleared on restart.

- [x] Unit-test the cap: points older than 30 minutes drop, and a new store is empty.
  - [x] **Security:** Tests build samples in memory. They open no sockets.
  - [x] **Docs:** No extra setup steps.

## 8. Parse metrics

Implement one parser per checkbox. Each takes fixture text and returns plain data. Each has a unit test.

- [x] CPU percent from two `/proc/stat` readings.
- [x] Load averages from `/proc/loadavg`.
- [x] Memory and swap from `/proc/meminfo`.
- [x] Mounts from `df -P` (size, used, available, use percent).
- [x] Per-interface bytes/sec from two `/proc/net/dev` readings, plus a total in and total out.
- [x] Top 10 processes by CPU and top 10 by memory from `ps` (user, pid, CPU percent, memory percent, command).
- [x] When only one reading exists, CPU and network are “waiting for next sample”.
  - [x] **Security:** Parsers accept command output text only. They do not build shell strings. Truncate oversized output before parsing. Treat process command text as untrusted data for the template.
  - [x] **Docs:** README copies the metric table from the PRD (what is read, and the fixed commands).

## 9. Fixed command collector

- [x] Define the command list as constants: `/proc/stat`, `/proc/loadavg`, `/proc/meminfo`, `df -P`, `/proc/net/dev`, and `ps`. Add a collector interface and a fake collector for tests.
  - [x] **Security:** The runner executes only those constants. Request data never selects a command. Use Paramiko’s exec channel later, not a local shell.
  - [x] **Docs:** README lists those commands and states the browser cannot replace them.

- [x] Unit-test that an unknown command is rejected and that the fake collector fills a sample.
  - [x] **Security:** The test proves rejection without opening a connection.
  - [x] **Docs:** No extra setup steps.

## 10. SSH collector

- [x] Implement the collector with Paramiko: password auth, 8 second timeout, fixed commands only.
  - [x] **Security:** Load host keys from the operator’s known_hosts and fail when the key is unknown. Do not log the password, the hash, or full command output. Close the client on every path.
  - [x] **Docs:** README says the target account only needs to read proc files and run `df` and `ps`, and that the host key must already be trusted.

- [x] Unit-test success, timeout, and auth failure with a fake Paramiko client. CI stays offline.
  - [x] **Security:** Tests pass a dummy password and assert it never appears in the raised error string.
  - [x] **Docs:** README notes that GitHub Actions does not reach real servers.

## 11. Background poller

- [x] Start one poller thread with the app. Every 15 seconds, poll servers one after another and store a sample. A failure marks that server offline and the loop continues. No sample yet shows “pending”.
  - [x] **Security:** The poller is not an HTTP route. It reads hosts only from `data/servers.json`. One server’s timeout stays inside that server’s 8 second limit.
  - [x] **Docs:** README records the 15 second interval, the per-server timeout, and the pending/offline labels.

- [x] Unit-test the loop with a fake clock and a fake collector: two servers, the second failing, the first still stored.
  - [x] **Security:** The test does not start a real thread against the network.
  - [x] **Docs:** No extra setup steps.

## 12. Live server list

- [x] Fill each row from the latest sample: display name, host, status, CPU percent, memory percent, fullest disk, and the short error when offline.
  - [x] **Security:** Render with autoescape. Status text comes from the app’s own labels. A poll error shown in the row is a short sanitized message.
  - [x] **Docs:** README describes the columns and the link to the detail page.

- [x] Test pending, online, and offline rows from fixture samples.
  - [x] **Security:** Fixture host names include characters that must be escaped, and the test checks the escaped output.
  - [x] **Docs:** No extra setup steps.

## 13. Server detail

- [x] Add the detail page: summary, CPU and load, memory and swap, disk table, network table, and both process tables. Link back to the list.
  - [x] **Security:** Look up the server only by its stored id. An unknown id returns 404. Escape process command text. The page has no buttons that change the host.
  - [x] **Docs:** README lists the detail blocks in the same order as the PRD.

- [x] Test a known id, an unknown id, and the “waiting for next sample” state.
  - [x] **Security:** The unknown-id test uses a value that is not a file path.
  - [x] **Docs:** No extra setup steps.

## 14. Charts

- [x] Add three Chart.js line charts on the detail page: CPU percent, used memory percent, and total network in/out. Feed them from the in-memory window.
  - [x] **Security:** Load Chart.js from the CDN URL recorded in the PRD, with a Subresource Integrity hash. Pass points through Jinja’s `tojson`. Cap the series at the 30 minute store.
  - [x] **Docs:** README names the three charts and the 30 minute window.

- [x] Test that the detail JSON contains the fixture points and omits SSH fields.
  - [x] **Security:** The assertion fails if `password` appears in the page payload.
  - [x] **Docs:** No extra setup steps.

## 15. Acceptance pass

- [ ] Walk `docs/requirements.md` section 10 on this machine: sign-out redirect, good and bad password, add a reachable Linux host, see metrics and charts, confirm an unreachable host stays offline, confirm the UI cannot edit, delete, or run a command, restart and confirm the server list remains while charts are empty.
  - [ ] **Security:** Use a low-privilege SSH account. Confirm `.env` and `data/servers.json` are untracked. Confirm the process is bound to `127.0.0.1:5000`.
  - [x] **Docs:** Check the README against section 9 of the PRD and adjust it so the local steps match what you just ran.
