# MarosimGo AI Fashion Studio — live AI virtual try-on

Real-time virtual try-on in `frontend-user` (`/ai-studio`), powered by Decart's realtime
`lucy-vton` model (the same model family behind anywear.decart.ai). The user's camera is streamed
to Decart over WebRTC. Decart streams back the user wearing the chosen garment, and that stream is
the only thing shown as the result. Without a configured provider the page says the feature is off.
It never falls back to a fake overlay or a canned video.

The older camera-AR try-on (`/kiyib-korish`, 2D layers drawn in the browser) is a separate,
independent feature and is unchanged.

## How it works

```
browser (frontend-user /ai-studio)                Django (apps.virtual_tryon)            Decart
──────────────────────────────────                ───────────────────────────            ──────
consent + getUserMedia (camera, no mic)
POST /api/v1/virtual-tryon/ai-sessions/ {consent} → limits checked, session row
                                                    (expires_at fixed)
@decartai/sdk realtime.connect(stream, …)
  apiKeyProvider() ─ POST …/ai-sessions/{id}/token/ → POST /v1/client/tokens ───────────→ ek_… (60 s)
  ←──────────────────────────────────────────────── short-lived client token only
  WebRTC (LiveKit) camera ⇄ processed stream ───────────────────────────────────────────→ lucy-vton-latest
switch garment: client.setImage(blob, {prompt})     (same connection, no reconnect)
capture: draw the *remote* <video> frame → POST …/looks/ (only on "Saqlash")
end / hidden tab / expiry: disconnect, stop tracks, POST …/ai-sessions/{id}/finish/ {reason, metrics}
```

* **The permanent `DECART_API_KEY` never leaves the server.** The browser only gets client tokens,
  each restricted to the model, the allowed origins and the seconds the session has left
  (`constraints.realtime.maxSessionDuration`). The SDK asks for a new one before every dial and reconnect.
* **No video reaches the MarosimGo server.** Only numeric metrics do (connect time, first frame, glass-to-glass
  latency, fps, interruptions, generated seconds), plus the single frame a user explicitly saves.
* Verified against Decart's docs (docs.platform.decart.ai) and `@decartai/sdk@0.2.14` types on
  2026-11-25: token endpoint and fields, `lucy-vton-latest` → `lucy-vton-3.6` (720p, $0.02/s realtime),
  `connect` options, `setImage(image, { prompt, enhance })`, `connectionChange` states, `error`
  codes (`WEBRTC_*`, `TOKEN_EXPIRED`, …) and `sessionEnded` reasons.

Code map:

| Piece | File |
| --- | --- |
| Decart HTTP client (token minting only) | `backend/apps/virtual_tryon/decart.py` |
| Session lifecycle, budgets, cost limits | `backend/apps/virtual_tryon/ai.py` |
| Reference-image validation | `backend/apps/virtual_tryon/reference.py` |
| User / admin API | `backend/apps/virtual_tryon/views.py`, `admin_views.py` |
| Live check / bulk catalogue import | `management/commands/check_ai_tryon.py`, `import_ai_garments.py` |
| Session state machine (framework-free, unit-tested) | `frontend-user/src/features/ai-studio/session.ts` |
| Studio UI (camera, SDK wiring, picker, capture, saved looks) | `frontend-user/src/features/ai-studio/studio.tsx` |
| API hooks | `frontend-user/src/lib/ai-tryon.ts` |

## Setup

1. **Get a Decart API key.** Create an account at https://platform.decart.ai, add credits, and create an
   API key under *API keys*. The account needs access to realtime `lucy-vton`.
2. **Configure the backend** (`backend/.env`, never a frontend `.env`). See `.env.example` for all names:

   ```
   DECART_API_KEY=<your key>
   DECART_TRYON_MODEL=lucy-vton-latest
   DECART_ALLOWED_ORIGINS=http://localhost:3002,http://127.0.0.1:3002   # production: https://your-user-app-origin
   ```

   `DECART_ALLOWED_ORIGINS` must be canonical origins (scheme + host [+ non-default port], lowercase,
   no trailing slash). Otherwise Decart rejects the token request with HTTP 422.
3. **Check the key** (mints one token; no video, no cost):

   ```
   cd backend
   python manage.py migrate
   python manage.py check_ai_tryon
   ```

4. **Load real garments.** See [Catalogue](#catalogue).
5. **Run:** `python manage.py runserver 127.0.0.1:8000` and, in `frontend-user`, `npm run dev`
   (port 3002). Open http://localhost:3002/ai-studio as a USER account. The camera needs a secure
   context: `localhost` works, and other hosts need HTTPS (mobile testing on the LAN too).

## Catalogue

Sections (migrations `0002` + `0005`). Each has an audience used by the studio's filter:

* **Men:** Kuyovlik kostyumlari (wedding suits), Smokinglar (tuxedos), Erkaklar ko'ylaklari (shirts),
  Chopon (chapan), Erkaklar milliy liboslari, Erkaklar kiyimlari.
* **Women:** Kelinlik liboslari (wedding dresses), Kechki liboslar (evening), Ayollar milliy liboslari,
  Atlas va adras liboslar, Hijob va aksessuarlar, Ayollar kiyimlari.
* **Unisex:** Milliy to'y liboslari, Boshqa kiyimlar.

A garment appears in the AI studio only when it is **active, APPROVED and has an `ai_reference_image`**.
The repository ships **no garment photos**. Use real, licensed product photos, either:

* **Admin panel / API:** `POST /api/v1/admin/virtual-tryon/garments/{id}/ai-reference/` (multipart
  `image`, optional `ai_prompt`), then `…/approve/`.
* **Bulk:** `python manage.py import_ai_garments <folder> [--dry-run] [--approve]` with a `manifest.json`
  (format in the command's docstring).

Reference image rules (Decart: "clean garment image, no person, white/plain background, ≥512×512"),
enforced by `reference.process_reference`:

* JPEG, PNG or WebP, ≤ 10 MB upload, fully decoded (decompression-bomb guarded).
* Shorter side ≥ 512 px. Aspect ratio between 1:3 and 3:1.
* Plain background: the border is near-white or a single uniform colour.
* Stored re-encoded: EXIF stripped, alpha flattened on white, ≤ 2048 px, JPEG q90.
* **Not machine-checked:** that no person is wearing the garment. Staff confirm this before approving.

`ai_prompt` (optional, ≤ 300 chars) is sent with the image, e.g. *"Substitute the current outfit with
a white satin wedding dress with long lace sleeves"*. It helps with garments the image alone
describes poorly (long dresses, chapan length).

## API

User endpoints (USER role, `/api/v1/`):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `virtual-tryon/categories/` | Active sections with garment counts |
| GET | `virtual-tryon/garments/?ai=1&category=&audience=&q=` | AI-ready garments |
| GET | `virtual-tryon/garments/{id}/` | Garment detail |
| GET | `virtual-tryon/ai/status/` | Enabled?, model, today's remaining seconds/sessions, active session |
| POST | `virtual-tryon/ai-sessions/` | Start a session (`{"consent": true}` required). 409 if one is active, 429 on limits, 503 if not configured |
| GET | `virtual-tryon/ai-sessions/{id}/` | Own session |
| POST | `virtual-tryon/ai-sessions/{id}/token/` | Short-lived Decart client token (410 when ended/expired) |
| POST | `virtual-tryon/ai-sessions/{id}/finish/` | End with `reason` + measured `metrics` |
| GET/POST | `virtual-tryon/looks/` | List / save a captured AI frame (multipart `image`, `garment`, `session`) |
| GET | `virtual-tryon/looks/{id}/image/` | Owner-only image (private storage, `no-store`) |
| DELETE | `virtual-tryon/looks/{id}/` | Delete a saved look and its file |

Admin: `admin/virtual-tryon/garments/…` (CRUD, `ai-reference`, `approve`, `reject`) and
`admin/virtual-tryon/ai-usage/` (sessions, seconds, estimated cost, measured metrics).
Full schema: `docs/openapi.yaml`.

## Cost and abuse controls

Decart bills each second of active generation. All limits are environment variables (`.env.example`):

| Setting | Default | Effect |
| --- | --- | --- |
| `AI_TRYON_MAX_SESSION_SECONDS` | 180 | Wall-clock cap per session (also sent to Decart as `maxSessionDuration`) |
| `AI_TRYON_DAILY_SECONDS_PER_USER` | 900 | Daily budget per user; a session is shortened to what is left |
| `AI_TRYON_DAILY_SESSIONS_PER_USER` | 10 | Sessions per user per day |
| `AI_TRYON_GLOBAL_DAILY_SECONDS` | 0 (off) | Platform-wide daily cap |
| `AI_TRYON_MAX_TOKENS_PER_SESSION` | 20 | Reconnect budget per session |
| `DECART_TOKEN_TTL_SECONDS` | 60 | Client-token lifetime (only needed to *start* a connection) |
| `THROTTLE_AI_TRYON_SESSION` / `_TOKEN` / `THROTTLE_TRYON_LOOK` | 20/h, 60/h, 60/h | Request rate limits |
| `AI_TRYON_MAX_SAVED_LOOKS` | 50 | Saved looks per user |

Also enforced: one ACTIVE session per user (DB constraint), and generation stops when the tab is
hidden or the page is left.

## Live test (needs a real key, a camera and HTTPS or localhost)

`check_ai_tryon` proves the key and the network path. The stream itself can only be verified in a browser:

1. Open `/ai-studio`, tick consent, then **Kamerani yoqish**. The raw preview is labelled *"oddiy kamera, AI emas"*.
2. Pick a garment, then **AI bilan kiyib ko'rish**. The states go *Seans ochilmoqda → AI'ga ulanmoqda →
   AI qayta ishlamoqda → Jonli AI*. Only in *Jonli AI* is the remote (Decart) stream shown.
3. Turn and move: the garment should follow. Pick another garment and confirm it changes without a reconnect.
4. Press the camera button, then **Saqlash**. The look appears under *Saqlangan obrazlarim*. Delete it.
5. Switch tabs: the state becomes *To'xtatildi*. Press **Yakunlash**: the camera light goes off.
6. `GET /api/v1/admin/virtual-tryon/ai-usage/` counts the session and its seconds, and under `measured`
   averages the client-reported metrics (`connect_ms_avg`, `first_frame_ms_avg`, …). Read those numbers
   from your own run. No FPS or latency is promised.

## Limitations

* The AI studio is web-only (desktop and mobile browsers with WebRTC: recent Chrome, Edge, Firefox,
  Safari/iOS). There is no native mobile app. React Native would need the SDK's own RN setup.
* Output quality, latency and FPS depend on Decart and on the user's uplink (a stable ~4 Mbit/s or
  better is advised). Decart may queue a session when it lacks capacity.
* Garment reference photos must be supplied by the business. None are bundled.
