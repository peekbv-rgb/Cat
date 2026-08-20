# Runway Character - live Session

Minimal end-to-end integration of Character `761a6d44-1be3-42d5-9bda-f5ef72a72e43`
using the documented Sessions lifecycle.

## Setup

### Configuration

All settings live in a single file, `.env`, in this directory. There is
deliberately no `.env.example`: two near-identically named files invite putting
real credentials in the one that gets distributed.

| Variable | Meaning |
|---|---|
| `RUNWAYML_API_SECRET` | Your API key. Required. |
| `RUNWAY_CHARACTER_ID` | Character to dial. Defaults to Cat Kadashian. |
| `PORT` | Listen port. Default `8000`. |
| `HOST` | Bind address. `127.0.0.1` default; `0.0.0.0` to expose on the LAN. |
| `RUNWAY_MAX_DURATION` | Call cap in seconds, 10-1800. Default `1800`. |
| `AUTH_USER` / `AUTH_PASSWORD` | Set both to require a browser login. |

A minimal `.env`:

```
RUNWAYML_API_SECRET=your_key_here
AUTH_USER=your_name
AUTH_PASSWORD=your_password
```

`.env` is gitignored and excluded from the zip. The build refuses to package if
any value from it appears in an archived file.

1. Install dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Create `.env` as shown above. The key is read server-side only and is never
   sent to the browser.

3. Run it:

   ```
   python server.py
   ```

4. Open http://localhost:8000 and click **Start call**. Allow microphone access.

## How it works

`server.py` owns the whole lifecycle; the browser only ever sees a short-lived
room token.

| Step | Call |
|---|---|
| Create | `client.realtime_sessions.create(model="gwm1_avatars", avatar={"type":"custom","avatar_id":...})` |
| Poll | `client.realtime_sessions.retrieve(id)` until `status == "READY"` |
| Consume | `POST /v1/realtime_sessions/{id}/consume` with `Authorization: Bearer <sessionKey>` |
| Connect | browser joins the returned LiveKit `url` + `token` |
| End | `client.realtime_sessions.delete(id)` |

Statuses: `NOT_READY` -> `READY` -> `RUNNING` -> `COMPLETED`, or `FAILED` / `CANCELLED`.

## Password protection

Set both `AUTH_USER` and `AUTH_PASSWORD` in `.env` and the server demands HTTP
Basic auth before serving anything - the page, the API, and static assets alike.
Leave either blank to disable.

Do this whenever the app is exposed through a tunnel: a quick-tunnel URL is
public, and without a gate anyone holding it can burn your credits. Basic auth
sends the password with every request, so only use it over HTTPS - which the
tunnel provides, and `localhost` does not need.

Credentials are compared with `hmac.compare_digest`, and live only in `.env`,
which is gitignored and excluded from the zip.

## Microphone

Pick your input from the **Microphone** dropdown, and use **Test mic** to check it
without opening a billed session - the blue bar moves when the device hears you.

The choice is remembered by id, name, and position, in that order. Browsers rotate
device ids when permission state changes and only reveal real device names after
permission is granted, so an id-or-name-only match silently falls back to the
default device - which is how a working call becomes a silent one on restart.

## The character interrupts itself

If the character stops mid-sentence, or never seems to hear you, the usual cause
is acoustic echo: the device plays the character through its speaker, its own mic
picks that up, and the pipeline's barge-in detection treats the character's voice
as you starting to talk - so it cuts itself off.

The mic is requested with `echoCancellation`, `noiseSuppression` and
`autoGainControl` enabled, which handles most cases. On a phone using its
loudspeaker it can still leak through - **use headphones or earbuds** and it goes
away entirely.

The microphone is also acquired inside the click handler, before the session is
provisioned. iOS Safari revokes transient user activation across awaits, so
asking afterwards is refused without ever showing a prompt. A useful side effect:
no session is created, and nothing bills, until the permission question resolves.

## Deploying to Render

`render.yaml` describes the service, so Render configures itself from the repo.

1. Push this repo to GitHub.
2. On Render: **New > Blueprint**, pick the repo. It reads `render.yaml`.
3. Set the two secret values in the Render dashboard (they are marked
   `sync: false`, so they are never stored in the repo):
   - `RUNWAYML_API_SECRET`
   - `AUTH_PASSWORD`
4. Deploy. Render gives an HTTPS URL, which is a secure context - so the
   microphone works on a phone with no tunnel involved.

Notes:

- `HOST=0.0.0.0` is set for you. Render routes to the container's external
  interface, so the loopback default would refuse connections.
- Render injects `PORT`; the server already reads it.
- On the free plan the service sleeps when idle, so the first request after a
  quiet spell takes ~30-60s to wake. Sessions themselves are unaffected once up.
- Never commit `.env`. It is gitignored, and the API key belongs only in
  Render's environment settings.

## Running it from a phone

Two things block it, and only the first is trivial:

1. The server binds to loopback. Set `HOST=0.0.0.0` to expose it on your network.
2. Browsers only allow microphone access in a *secure context* - HTTPS, or the
   `localhost` special case. A LAN address over plain HTTP is neither, so on a
   phone `navigator.mediaDevices` is `undefined` and the mic cannot work at all.
   The page detects this and says so rather than failing cryptically.

So `http://<your-lan-ip>:8000` gets you the character's video, audio and
transcript on a phone, but no talking back. For a real conversation the page must
be served over HTTPS - easiest via a tunnel (`cloudflared tunnel --url
http://localhost:8000` or `ngrok http 8000`), which gives a public HTTPS URL that
counts as a secure context. Treat that URL as public while it is open.

## Two things to know

- **`consume` is one-shot.** Once credentials are issued the Session is spent. If
  the WebRTC handshake fails, create a new Session rather than retrying.
- **Sessions bill while the worker is active.** The client ends the Session on
  hang-up, on disconnect, and on `pagehide`; the server also cancels it if
  provisioning or connect fails.
- **Calls are time-capped.** Runway defaults to 300s, so an untuned call stops
  abruptly after five minutes. `RUNWAY_MAX_DURATION` sets the cap (10-1800s); this
  app requests 1800s and shows a live countdown with warnings at 60s and 15s.
  Raising the cap does not cost more by itself - it only raises the ceiling.
