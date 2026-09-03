# Long Live Latin

A deliberately simple Latin flashcard library with a browser-based content manager.

## Run with Docker

1. Copy `.env.example` to `.env`.
2. Generate a password hash:
   `python -c "import bcrypt; print(bcrypt.hashpw(b'choose-a-long-password', bcrypt.gensalt()).decode())"`
3. Set `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, and a long random `SECRET_KEY` in `.env`.
4. Start the application: `docker compose up -d --build`
5. Open `http://<server-ip>:8200` from another device, or `http://127.0.0.1:8200` on the Docker host. Put Caddy or another TLS reverse proxy in front for public use.

The default host port is `8200`, bound to `0.0.0.0` for LAN access. You can change `APP_PORT` or set `BIND_ADDRESS=127.0.0.1` in `.env` later without rebuilding the image. The application continues to listen on port `8000` inside its container.

The SQLite database is stored in the named `latin_data` volume and survives container replacement and restarts. The application is bound to localhost by default so it is not directly exposed to the internet.

## Local development

Create a virtual environment, install `requirements.txt`, set the variables from `.env.example`, then run `python app.py`.

The sample Level 1 lesson is inserted only when the database is empty. Delete it through Administration when it is no longer needed.

## Backups

Administration provides a JSON export of all levels, lessons, and flashcards, plus a restore form. Store downloaded backups away from the server. Restoring replaces all current course content.

## Security notes

- No password is committed. Startup without `ADMIN_PASSWORD_HASH` leaves admin login disabled.
- Passwords are checked using bcrypt; cookies are HttpOnly and SameSite=Lax. Set `COOKIE_SECURE=true` behind HTTPS.
- Admin mutations require a CSRF token and use parameterized SQL.
- Login is limited to five attempts per IP per 15-minute window.
- Run behind HTTPS and keep `.env` private in production.
