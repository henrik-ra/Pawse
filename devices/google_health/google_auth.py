"""One-time Google Health API login (OAuth2 authorization-code flow).

Run once:

    python devices/google_health/google_auth.py

It opens your browser, you sign in and click *Allow*, and the resulting tokens
(access + refresh) are stored in ``google_tokens.json`` next to this file.
After that the dashboard reads live data automatically and refreshes the token
on its own.

Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, either as environment
variables or in a local ``.env`` file in this folder (see .env.example).
"""
from __future__ import annotations

import http.server
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests

# Allow running directly (`python devices/google_health/google_auth.py`) by
# putting the repo root on sys.path so the `devices` package is importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from devices.google_health.google_health_client import (
    AUTH_URI,
    REDIRECT_URI,
    SCOPES,
    TOKEN_URI,
    load_credentials,
    save_tokens,
)

_CALLBACK_PORT = 8721


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures the ?code=... that Google sends back to the redirect URI."""

    auth_code: str | None = None
    expected_state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.error = params.get("error", [None])[0]
        state = params.get("state", [None])[0]

        if _CallbackHandler.error:
            message = f"Authorization failed: {_CallbackHandler.error}"
        elif state != _CallbackHandler.expected_state:
            _CallbackHandler.error = "state_mismatch"
            message = "Authorization failed: state mismatch (possible CSRF)."
        else:
            _CallbackHandler.auth_code = params.get("code", [None])[0]
            message = "Pawse is connected. You can close this tab."

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{message}</h2></body></html>".encode())

    def log_message(self, *args) -> None:  # silence default logging
        return


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    resp = requests.post(
        TOKEN_URI,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    client_id, client_secret = load_credentials()
    if not client_id or not client_secret:
        raise SystemExit(
            "Missing GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET. Set them as "
            "environment variables or in devices/google_health/.env"
        )

    state = secrets.token_urlsafe(16)
    _CallbackHandler.expected_state = state

    auth_url = AUTH_URI + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",      # request a refresh token
            "prompt": "consent",           # force refresh token on re-consent
            "include_granted_scopes": "true",
            "state": state,
        }
    )

    print("Opening your browser to sign in with Google...")
    print("If it does not open, paste this URL manually:\n")
    print(auth_url, "\n")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", _CALLBACK_PORT), _CallbackHandler)
    print(f"Waiting for the redirect on {REDIRECT_URI} ...")
    while _CallbackHandler.auth_code is None and _CallbackHandler.error is None:
        server.handle_request()

    if _CallbackHandler.error:
        raise SystemExit(f"Login failed: {_CallbackHandler.error}")

    tokens = _exchange_code(_CallbackHandler.auth_code, client_id, client_secret)
    save_tokens(tokens)
    print("\nSuccess. Tokens saved to google_tokens.json.")
    print("Run `python server.py` and open http://localhost:8000.")


if __name__ == "__main__":
    main()
