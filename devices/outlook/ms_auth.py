"""Microsoft Entra ID (Azure AD) OAuth2 login for Microsoft Graph.

Run once:

    python devices/outlook/ms_auth.py

It opens your browser, you sign in with your Microsoft 365 account,
and the resulting tokens (access + refresh) are stored in
``devices/outlook/ms_tokens.json``.

After that, the calendar and meeting APIs work automatically and refresh
the token on their own.

Requires MS_CLIENT_ID and (optionally) MS_CLIENT_SECRET, either as
environment variables or in a local ``.env`` file in this folder.
For a public/native client, only MS_CLIENT_ID is needed.
"""
from __future__ import annotations

import http.server
import json
import os
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests

_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# --- Constants ----------------------------------------------------------------

AUTHORITY = "https://login.microsoftonline.com/common"
AUTH_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/authorize"
TOKEN_ENDPOINT = f"{AUTHORITY}/oauth2/v2.0/token"
REDIRECT_URI = "http://localhost:8722/callback"
_CALLBACK_PORT = 8722

SCOPES = [
    "User.Read",
    "Calendars.Read",
    "Calendars.ReadWrite",
    "Mail.ReadWrite",
    "offline_access",
]

_TOKEN_PATH = _DIR / "ms_tokens.json"
_ENV_PATH = _DIR / ".env"


# --- Credential helpers -------------------------------------------------------

def load_credentials() -> tuple[str, str]:
    """Load MS_CLIENT_ID and MS_CLIENT_SECRET from env or .env file."""
    client_id = os.environ.get("MS_CLIENT_ID", "")
    client_secret = os.environ.get("MS_CLIENT_SECRET", "")

    if not client_id and _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key == "MS_CLIENT_ID":
                client_id = val
            elif key == "MS_CLIENT_SECRET":
                client_secret = val

    return client_id, client_secret


def load_tokens() -> dict | None:
    """Load saved tokens from disk."""
    if not _TOKEN_PATH.exists():
        return None
    try:
        return json.loads(_TOKEN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_tokens(tokens: dict) -> None:
    """Persist tokens to disk."""
    _TOKEN_PATH.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


def refresh_access_token(refresh_token: str) -> dict | None:
    """Use the refresh token to get a new access token."""
    client_id, client_secret = load_credentials()
    if not client_id:
        return None

    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": " ".join(SCOPES),
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=30)
        resp.raise_for_status()
        tokens = resp.json()
        # Preserve refresh_token if the response doesn't include a new one
        if "refresh_token" not in tokens:
            tokens["refresh_token"] = refresh_token
        save_tokens(tokens)
        return tokens
    except Exception:
        return None


def get_valid_access_token() -> str | None:
    """Return a valid access token, refreshing if needed."""
    tokens = load_tokens()
    if not tokens:
        return None

    # Try the existing access token first (we don't track expiry precisely,
    # so we'll let callers handle 401 and call refresh)
    return tokens.get("access_token")


def ensure_access_token() -> str | None:
    """Get access token, refreshing if the stored one is stale."""
    tokens = load_tokens()
    if not tokens:
        return None

    # Always try refresh to ensure we have a valid token
    refresh = tokens.get("refresh_token")
    if refresh:
        new_tokens = refresh_access_token(refresh)
        if new_tokens:
            return new_tokens.get("access_token")

    return tokens.get("access_token")


# --- OAuth2 callback handler --------------------------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Captures the ?code=... from Microsoft's redirect."""

    auth_code: str | None = None
    expected_state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.error = params.get("error", [None])[0]
        state = params.get("state", [None])[0]

        if _CallbackHandler.error:
            desc = params.get("error_description", [""])[0]
            message = f"Authorization failed: {_CallbackHandler.error} — {desc}"
        elif state != _CallbackHandler.expected_state:
            _CallbackHandler.error = "state_mismatch"
            message = "Authorization failed: state mismatch (possible CSRF)."
        else:
            _CallbackHandler.auth_code = params.get("code", [None])[0]
            message = "Pawse is connected to Microsoft 365. You can close this tab."

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            f"<html><body><h2>{message}</h2></body></html>".encode()
        )

    def log_message(self, *args) -> None:
        return


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange authorization code for tokens."""
    data = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
        "scope": " ".join(SCOPES),
    }
    if client_secret:
        data["client_secret"] = client_secret

    resp = requests.post(TOKEN_ENDPOINT, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


# --- CLI entry point ----------------------------------------------------------

def main() -> None:
    client_id, client_secret = load_credentials()
    if not client_id:
        raise SystemExit(
            "Missing MS_CLIENT_ID. Set it as an environment variable "
            "or in devices/outlook/.env\n\n"
            "Register an app at https://entra.microsoft.com → App registrations.\n"
            "Add redirect URI: http://localhost:8722/callback\n"
            "Required API permissions (delegated): " + ", ".join(SCOPES)
        )

    state = secrets.token_urlsafe(16)
    _CallbackHandler.expected_state = state

    auth_url = AUTH_ENDPOINT + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(SCOPES),
            "response_mode": "query",
            "state": state,
            "prompt": "consent",
        }
    )

    print("Opening your browser to sign in with Microsoft...")
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
    print("\nSuccess. Tokens saved to devices/outlook/ms_tokens.json.")
    print("Run `python server.py` and the calendar features will work automatically.")


if __name__ == "__main__":
    main()
