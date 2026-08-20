"""Runway Characters - live Session backend.

Creates a realtime Session for a Character, polls it to READY, consumes the
one-time WebRTC credentials, and hands only those to the browser.

RUNWAYML_API_SECRET never leaves this process - the browser receives a
short-lived room token, never the API key.
"""

import base64
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from dotenv import load_dotenv
from runwayml import RunwayML

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

load_dotenv(ROOT / ".env")

CHARACTER_ID = os.environ.get(
    "RUNWAY_CHARACTER_ID", "761a6d44-1be3-42d5-9bda-f5ef72a72e43"
)
PORT = int(os.environ.get("PORT", "8000"))
# Loopback by default. Set HOST=0.0.0.0 to reach it from a phone on the same
# network - but note browsers block microphone access on a plain-HTTP LAN
# address, so a phone needs an HTTPS tunnel to actually hold a conversation.
HOST = os.environ.get("HOST", "127.0.0.1")

# Optional gate. Set both to require a browser login before anything is served -
# worth it whenever the app is exposed through a tunnel.
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASSWORD = os.environ.get("AUTH_PASSWORD", "")
AUTH_ENABLED = bool(AUTH_USER and AUTH_PASSWORD)
RUNWAY_VERSION = "2024-11-06"

# Sessions default to 300s server-side. The API accepts 10-1800.
MAX_DURATION = max(10, min(1800, int(os.environ.get("RUNWAY_MAX_DURATION", "1800"))))

# Provisioning runs NOT_READY -> READY, normally within a few seconds.
POLL_TIMEOUT_S = 60
POLL_INTERVAL_S = 1.0

def _warn_if_template_has_secrets() -> None:
    """The template ships in the zip - values in it are a disclosure risk.

    Easy to hit by editing .env.example instead of .env, since the app keeps
    working either way (the real values come from .env).
    """
    template = ROOT / ".env.example"
    if not template.is_file():
        return
    leaked = []
    for line in template.read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key in ("RUNWAYML_API_SECRET", "AUTH_USER", "AUTH_PASSWORD") and value.strip():
            leaked.append(key)
    if leaked:
        print("!" * 68, flush=True)
        print("WARNING  .env.example contains real values for: " + ", ".join(leaked), flush=True)
        print("         That file is a blank template and is distributed with the", flush=True)
        print("         project. Clear those lines and put values in .env instead.", flush=True)
        print("!" * 68, flush=True)


_warn_if_template_has_secrets()

if not os.environ.get("RUNWAYML_API_SECRET"):
    raise SystemExit(
        "RUNWAYML_API_SECRET is not set.\n"
        "Copy .env.example to .env and put your key there, then rerun."
    )

client = RunwayML()


def create_session() -> str:
    """Create a Session bound to our Character and return its id."""
    created = client.realtime_sessions.create(
        model="gwm1_avatars",
        avatar={"type": "custom", "avatar_id": CHARACTER_ID},
        max_duration=MAX_DURATION,
    )
    return created.id


def wait_until_ready(session_id: str) -> tuple[str, str | None]:
    """Poll until READY; return (sessionKey, createdAt) or raise with the reason."""
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        session = client.realtime_sessions.retrieve(session_id)
        status = session.status

        if status == "READY":
            # createdAt anchors the countdown: the cap is measured from session
            # creation, not from when the browser connects.
            created = getattr(session, "created_at", None)
            return session.session_key, (created.isoformat() if created else None)
        if status == "FAILED":
            raise RuntimeError(f"{session.failure_code}: {session.failure}")
        if status in ("CANCELLED", "COMPLETED"):
            raise RuntimeError(f"Session ended before connect (status {status})")

        time.sleep(POLL_INTERVAL_S)

    raise TimeoutError(f"Session {session_id} was not READY after {POLL_TIMEOUT_S}s")


def consume_credentials(session_id: str, session_key: str) -> dict:
    """Exchange the sessionKey for WebRTC credentials.

    This is a one-shot endpoint. If the browser's WebRTC handshake fails after
    this call, the Session is spent - create a new one rather than retrying.
    """
    response = httpx.post(
        f"{client.base_url}/v1/realtime_sessions/{session_id}/consume",
        headers={
            "Authorization": f"Bearer {session_key}",
            "X-Runway-Version": RUNWAY_VERSION,
        },
        # httpx sends a zero-length body here; without an explicit JSON body the
        # API rejects the request with "Incorrect content type".
        json={},
        timeout=30,
    )
    if response.status_code >= 400:
        # Surface the API's reason rather than a bare status code.
        raise RuntimeError(f"consume failed ({response.status_code}): {response.text}")
    return response.json()


def end_session(session_id: str) -> None:
    """Cancel a Session so the Character worker stops billing."""
    client.realtime_sessions.delete(session_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "RunwayCharacterDemo/1.0"

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        """Check HTTP Basic credentials in constant time."""
        if not AUTH_ENABLED:
            return True

        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
            user, _, password = decoded.partition(":")
        except Exception:
            return False

        # compare_digest on both halves so neither leaks via timing.
        return hmac.compare_digest(user, AUTH_USER) and hmac.compare_digest(
            password, AUTH_PASSWORD
        )

    def _challenge(self) -> None:
        body = b"Authentication required."
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Runway Character", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        # Handled ahead of auth: these are unauthenticated browser probes, and
        # challenging them just produces repeated 401s in the log.
        if self._is_icon_probe(path):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return

        if not self._authorized():
            self._challenge()
            return
        if path in ("/", "/index.html"):
            self._send_file(STATIC / "index.html", "text/html; charset=utf-8")
        elif path == "/api/character":
            self._handle_character()
        elif path.startswith("/static/"):
            self._handle_static(path[len("/static/"):])
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if not self._authorized():
            self._challenge()
            return
        if self.path == "/api/session":
            self._handle_create()
        elif self.path.startswith("/api/session/") and self.path.endswith("/end"):
            session_id = self.path[len("/api/session/"):-len("/end")]
            self._handle_end(session_id)
        else:
            self._send_json({"error": "not found"}, 404)

    TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".css": "text/css", ".js": "text/javascript"}

    @staticmethod
    def _is_icon_probe(path: str) -> bool:
        """Safari probes for touch icons on every page load; we have none."""
        return path == "/favicon.ico" or path.startswith("/apple-touch-icon")

    def log_request(self, code="-", size="-"):
        # Keep icon probes out of the log - they are noise, not events.
        if self._is_icon_probe(self.path.split("?", 1)[0]):
            return
        super().log_request(code, size)

    def _handle_static(self, name: str) -> None:
        target = (STATIC / name).resolve()
        # Refuse anything that escapes the static directory.
        if STATIC.resolve() not in target.parents or not target.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        self._send_file(target, self.TYPES.get(target.suffix, "application/octet-stream"))

    def _handle_character(self) -> None:
        """Confirm the Character exists and the key works, before dialling."""
        try:
            avatar = client.avatars.retrieve(CHARACTER_ID)
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 502)
            return
        self._send_json(
            {
                "id": CHARACTER_ID,
                "name": getattr(avatar, "name", None),
                "status": getattr(avatar, "status", None),
            }
        )

    def _handle_create(self) -> None:
        session_id = None
        try:
            session_id = create_session()
            self.log_message("created session %s", session_id)

            session_key, created_at = wait_until_ready(session_id)
            self.log_message("session %s READY (created %s)", session_id, created_at)

            credentials = consume_credentials(session_id, session_key)
            self.log_message("consumed credentials for %s", session_id)
        except Exception as exc:
            # Never leave a provisioned worker running after a failed connect.
            if session_id:
                try:
                    end_session(session_id)
                except Exception:
                    pass
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 502)
            return

        self._send_json(
            {
                "sessionId": session_id,
                "serverUrl": credentials["url"],
                "token": credentials["token"],
                "roomName": credentials["roomName"],
                "createdAt": created_at,
                "maxDuration": MAX_DURATION,
            }
        )

    def _handle_end(self, session_id: str) -> None:
        try:
            end_session(session_id)
        except Exception as exc:
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, 502)
            return
        self.log_message("ended session %s", session_id)
        self._send_json({"ok": True})


if __name__ == "__main__":
    print(f"Character  {CHARACTER_ID}", flush=True)
    print(f"Max call   {MAX_DURATION}s ({MAX_DURATION // 60} min)", flush=True)
    print(f"Auth       {'ON (user ' + AUTH_USER + ')' if AUTH_ENABLED else 'OFF - anyone with the URL can use it'}", flush=True)
    print(f"Listening  http://{'localhost' if HOST == '127.0.0.1' else HOST}:{PORT}", flush=True)
    if HOST != "127.0.0.1":
        print("Warning    non-loopback bind: the mic needs HTTPS - fine if a proxy", flush=True)
        print("           terminates TLS (Render, Cloudflare), not over plain http://", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
