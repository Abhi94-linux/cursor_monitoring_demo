# Demo Server Monitoring — Software Requirements

## 1. Purpose

Build a small local web app so internal teams can see Linux server health without signing in to each machine.

The app runs on the same computer as this project. It is a demo, not a production monitoring system.

## 2. Problem

Today, L1, L2, and L3 check a server by logging in and reading memory, CPU, disk, network, and process state by hand. That is slow when several people need the same view.

## 3. Users

| Team | Need |
| --- | --- |
| L1 | See whether a server is up and which resource looks hot |
| L2 | Open one server and compare CPU, memory, disk, network, and processes |
| L3 / application developers | Confirm resource pressure on a host they do not manage day to day |

All of these teams share one sign-in. The demo does not separate roles.

## 4. Product rules

- The browser is read-only for server state. No one can restart a service, kill a process, or type a command.
- The only changes the signed-in user can make are signing in, signing out, and adding a server.
- Servers cannot be edited or removed in the UI.
- Metrics come from SSH. The app runs a fixed set of read-only commands. It does not open a shell for the user.
- Samples stay in memory for 30 minutes, then drop. Restarting the app clears charts. The server list is kept on disk.

## 5. Out of scope

- Listening ports, firewall rules, and connection tables
- Alerts, email, or tickets
- Multiple accounts, password change, or team-specific views
- Editing or deleting a server from the UI
- Agents installed on the servers
- History longer than 30 minutes, or history saved to a database
- Windows or other non-Linux hosts
- Anything other than `127.0.0.1` on the demo machine

## 6. Functional requirements

### 6.1 Sign in

1. Unauthenticated visitors see only the sign-in page.
2. The username is `admin`.
3. The app stores the password as a hash in a local environment file. It never stores or logs the plaintext password.
4. A correct password starts a session cookie. A wrong password shows a single error and stays on the sign-in page.
5. There is no screen to change the password. Replacing the hash means editing the env file and restarting the app.
6. Sign out clears the session.

### 6.2 Server list

1. After sign-in, the home page lists every added server.
2. Each row shows display name, host, online/offline, CPU percent, memory percent, and the fullest disk.
3. A row links to that server’s detail page.
4. The page reads the latest sample already in memory. It does not wait on SSH.
5. If a server has never been reached, the row says “pending” until the first poll finishes.
6. If the last poll failed, the row says “offline” and shows the short error from that poll.

### 6.3 Add a server

The add form asks for:

| Field | Rule |
| --- | --- |
| Display name | Required, shown in the UI |
| Host | Required hostname or IP |
| SSH port | Required, default `22` |
| SSH username | Required |
| SSH password | Required, used only to connect |

On save, the app appends the server to a local JSON file and returns to the list. The next poll (or an immediate first poll) fills the metrics. The form does not offer edit or delete.

SSH passwords must be reversible so the app can log in. Keep them only in that local JSON file, readable by the user running the app. This is acceptable for a demo on one machine.

### 6.4 Server detail

The detail page shows the latest sample and the in-memory history for that host.

| Block | Content |
| --- | --- |
| Summary | Name, host, port, status, last successful poll time, last error if any |
| CPU | Current percent and 1, 5, and 15 minute load averages. Line chart of CPU percent |
| Memory | Total, used, free, and swap used/total. Line chart of used memory percent |
| Disk | One row per mount: size, used, available, use percent |
| Network | One row per interface: current in and out bytes per second. One chart of total in and total out |
| Processes | Top 10 by CPU and top 10 by memory. Columns: user, pid, CPU percent, memory percent, command |

Charts use the samples kept for that server, one point per successful poll, for up to 30 minutes.

### 6.5 Collection

1. A background poller runs inside the Flask process. Page loads do not open SSH themselves.
2. Every 15 seconds the poller connects to each server, runs the command set below, and stores one sample.
3. SSH connect and command time is limited to 8 seconds per server. A slow host does not stop the others.
4. Commands are fixed. The app does not accept a command from the browser.

| Metric | Read from |
| --- | --- |
| CPU percent | Two reads of `/proc/stat`, compared between polls |
| Load average | `/proc/loadavg` |
| Memory and swap | `/proc/meminfo` |
| Disk | `df -P` |
| Network throughput | Two reads of `/proc/net/dev`, compared between polls |
| Processes | `ps` output, ranked in the app |

The first poll after a process start has no CPU or network rate yet. Show those two as “waiting for next sample” until the second poll.

Samples for a server live in a list capped at 30 minutes. With a 15 second interval that is about 120 points. The list is discarded when the app stops.

## 7. Screens

1. **Sign in** — username, password, submit.
2. **Server list** — table plus a link to add a server, and sign out.
3. **Add server** — the form in section 6.3.
4. **Server detail** — the blocks in section 6.4, with a link back to the list.

Use one simple layout: a header with the app name and sign out, a readable type size, and enough contrast to scan numbers quickly. No theme switcher.

## 8. Technical approach

| Piece | Choice |
| --- | --- |
| Language | Python 3 |
| Web | Flask, server-rendered pages |
| UI | Flask templates, one CSS file, Chart.js from a CDN for the three charts |
| SSH | Paramiko, password auth, fixed commands only |
| Admin password | Werkzeug hash in `.env` (`ADMIN_PASSWORD_HASH`) |
| Session | Flask signed cookie; `SECRET_KEY` in `.env` |
| Server list | `data/servers.json` on the demo machine |
| Metrics | Process memory only |

Bind the app to `127.0.0.1` port `5000`.

Expected demo size is up to about 10 servers. Poll them one after another inside the 15 second cycle.

## 9. Run locally

From the project directory:

1. Create a virtual environment and install dependencies from `requirements.txt`.
2. Copy `.env.example` to `.env`.
3. Set `SECRET_KEY` to any long random string.
4. Generate `ADMIN_PASSWORD_HASH` with Werkzeug’s `generate_password_hash` and put that hash in `.env`. The sign-in name is `admin`.
5. Start the app so it listens on `127.0.0.1:5000`.
6. Open `http://127.0.0.1:5000`, sign in, and add a Linux host that accepts the SSH user and password from the form.

The target account only needs permission to read the proc files and run `df` and `ps`. It does not need root.

## 10. Acceptance

- Visiting any page while signed out redirects to sign in.
- `admin` plus the password that matches the hash opens the server list. A wrong password does not.
- Adding a reachable Linux server makes it appear on the list, then shows live CPU, memory, disk, network, and process data after polling.
- The detail page charts CPU, memory, and total network for the samples collected in the last 30 minutes.
- An unreachable host stays on the list as offline and does not break the other servers.
- The UI has no control to edit a server, remove a server, or run a custom command.
- Restarting the app keeps the server list and clears chart history.
- The app is usable from a browser on the demo machine at `http://127.0.0.1:5000`.
