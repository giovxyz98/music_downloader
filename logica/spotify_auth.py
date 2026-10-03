import base64
import json
import threading
import time

import requests

from .config import logger, ROOT_DIR

_SECRETS_FILE = ROOT_DIR / "secrets.json"
_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Anticipo di rinnovo rispetto alla scadenza reale del token, per non
# rischiare una richiesta API con un token già spirato a metà volo.
_EXPIRY_MARGIN = 60


class SpotifyAuth:
    """Client Credentials flow: ottiene e rinnova automaticamente l'access
    token Spotify, condiviso e thread-safe tra tutte le chiamate di ricerca."""

    def __init__(self):
        try:
            with open(_SECRETS_FILE, "r", encoding="utf-8") as f:
                secrets = json.load(f)
        except FileNotFoundError:
            raise RuntimeError(
                f"{_SECRETS_FILE} non trovato: creare il file con "
                '{"client_id": "...", "client_secret": "..."} (credenziali Spotify Developer Dashboard)'
            )
        self._client_id     = secrets["client_id"]
        self._client_secret = secrets["client_secret"]

        self._lock       = threading.Lock()
        self._token: str = ""
        self._expires_at: float = 0.0

    def _fetch_token(self) -> None:
        creds   = f"{self._client_id}:{self._client_secret}".encode("utf-8")
        b64     = base64.b64encode(creds).decode("ascii")
        headers = {"Authorization": f"Basic {b64}"}
        data    = {"grant_type": "client_credentials"}
        logger.debug("[Spotify][Auth] Richiesta nuovo access token")
        r = requests.post(_TOKEN_URL, headers=headers, data=data, timeout=30)
        r.raise_for_status()
        body = r.json()
        self._token      = body["access_token"]
        self._expires_at = time.time() + body.get("expires_in", 3600)
        logger.debug(f"[Spotify][Auth] Token ottenuto, valido {body.get('expires_in', 3600)}s")

    def get_token(self) -> str:
        with self._lock:
            if not self._token or time.time() >= self._expires_at - _EXPIRY_MARGIN:
                self._fetch_token()
            return self._token

    def force_refresh(self) -> str:
        with self._lock:
            self._fetch_token()
            return self._token
