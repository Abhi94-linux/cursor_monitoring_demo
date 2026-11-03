# Server Monitor

Local demo so internal teams can read Linux server health from one browser on this machine.

## Run locally

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
8. Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

The app listens on `127.0.0.1` port `5000` only. It will not start until both `SECRET_KEY` and `ADMIN_PASSWORD_HASH` are set.

There is no password-change screen. Replacing the hash means editing `.env` and restarting the app.

## Sign in

The sign-in page asks for a username and password. Only `admin` with the password that matches `ADMIN_PASSWORD_HASH` opens a session. A wrong username and a wrong password show the same error.

After sign-in, the header shows **Sign out**. Sign out clears the session only. It does not change the stored hash.

## Placeholder page

The home page, after sign-in, is a placeholder card titled “Linux server monitoring demo”. It does not list servers or take any server action yet.

Layout:

- Header with “Server monitoring”, “Local demo”, and **Sign out** while the session is active
- One stylesheet, `static/style.css`
- One white card under that header

There is no theme switch. Jinja autoescape stays on. The pages load no external script.

## Tests

```bash
python -m unittest discover -s tests
```
