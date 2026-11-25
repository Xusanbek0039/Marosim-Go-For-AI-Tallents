// End-to-end WRITE workflows through the real Next.js proxies (complements smoke-panels.mjs, which
// covers reads). Run only against the disposable audit servers started from tools/qa_backend.py:
//   python tools/qa_backend.py setup && python tools/qa_backend.py          (Django on :8100)
//   BACKEND_URL=http://127.0.0.1:8100 next start -p 3100|3101|3102|3103      (admin|user|studio|venue)
//   node tools/smoke-workflows.mjs
// Steps that need Google Drive credentials are reported as such, never as passed.
import assert from "node:assert/strict";

const PASSWORD = "Local-Audit-2026!";
const PANELS = { admin: 3100, user: 3101, studio: 3102, venue: 3103 };
const results = [];

function session(port) {
  const origin = `http://127.0.0.1:${port}`;
  const jar = new Map();
  async function call(method, path, { body, expect } = {}) {
    const csrf = [...jar].find(([key]) => key.endsWith("csrftoken"))?.[1];
    const response = await fetch(origin + "/api/v1" + path, {
      method,
      redirect: "manual",
      headers: {
        Origin: origin,
        Cookie: [...jar].map(([k, v]) => `${k}=${v}`).join("; "),
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(csrf && method !== "GET" ? { "X-CSRFToken": csrf } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    for (const cookie of response.headers.getSetCookie()) {
      const pair = cookie.split(";", 1)[0];
      const at = pair.indexOf("=");
      const value = pair.slice(at + 1);
      if (value === "" || /max-age=0/i.test(cookie)) jar.delete(pair.slice(0, at));
      else jar.set(pair.slice(0, at), value);
    }
    const text = await response.text();
    const data = text ? JSON.parse(text) : null;
    if (expect !== undefined) {
      assert.equal(response.status, expect, `${method} ${path} on :${port} -> ${response.status} ${text.slice(0, 200)}`);
      results.push(`${method} ${path} (:${port}) -> ${response.status}`);
    }
    return { status: response.status, data };
  }
  return {
    call,
    async login(phone) {
      await call("GET", "/auth/csrf/", { expect: 200 });
      const { data } = await call("POST", "/auth/login/", { body: { phone_number: phone, password: PASSWORD }, expect: 200 });
      return data.user;
    },
  };
}

const inDays = (n) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);

// 1) Registration -> login -> me -> logout -> session is gone.
{
  const s = session(PANELS.user);
  const phone = `+99890${String(Date.now()).slice(-7)}`;
  await s.call("GET", "/auth/csrf/", { expect: 200 });
  await s.call("POST", "/auth/register/", {
    body: { phone_number: phone, password: PASSWORD, password_confirm: PASSWORD, first_name: "E2E", last_name: "Sinov" },
    expect: 201,
  });
  const user = await s.login(phone);
  assert.equal(user.role, "USER");
  assert.equal((await s.call("GET", "/auth/me/", { expect: 200 })).data.phone_number, phone);
  await s.call("POST", "/auth/logout/", { expect: 204 });
  await s.call("GET", "/auth/me/", { expect: 401 });
  console.log("registration, login, logout: passed");
}

// 2) Role restrictions are enforced by the API, not only by the UI.
{
  const anon = session(PANELS.user);
  await anon.call("GET", "/auth/me/", { expect: 401 });
  const user = session(PANELS.user);
  await user.login("+998901110005");
  await user.call("GET", "/users/", { expect: 403 });
  await user.call("POST", "/ceremonies/", { body: { title: "x", event_date: inDays(5) }, expect: 403 });
  const studio = session(PANELS.studio);
  await studio.login("+998901110003");
  await studio.call("GET", "/users/", { expect: 403 });
  const admin = session(PANELS.admin);
  await admin.login("+998901110002");
  await admin.call("GET", "/users/", { expect: 200 });
  await admin.call("GET", "/admins/", { expect: 403 }); // only the Super Admin manages admins
  console.log("role restrictions: passed");
}

// 3) Studio creates a ceremony; media upload without Google Drive answers with a clean error.
{
  const studio = session(PANELS.studio);
  await studio.login("+998901110003");
  const { data: ceremony } = await studio.call("POST", "/ceremonies/", {
    body: { title: "E2E To'y", event_type: "WEDDING", event_date: inDays(20) },
    expect: 201,
  });
  const list = (await studio.call("GET", "/ceremonies/", { expect: 200 })).data;
  assert.ok((list.results ?? list).some((c) => c.id === ceremony.id), "created ceremony is listed");
  const upload = await studio.call("POST", `/ceremonies/${ceremony.id}/media/uploads/`, {
    body: { filename: "a.jpg", mime_type: "image/jpeg", size_bytes: 1024 },
  });
  assert.ok(upload.status >= 400 && upload.status < 600 && upload.data?.error?.code, "structured error");
  results.push(`POST /ceremonies/{id}/media/uploads/ (:3102) -> ${upload.status} ${upload.data.error.code}`);
  console.log(`ceremony creation: passed; media upload: REQUIRES GOOGLE DRIVE (got ${upload.status} ${upload.data.error.code})`);
}

// 4) Booking: a couple requests a hall session, the venue owner confirms it.
{
  const user = session(PANELS.user);
  await user.login("+998901110005");
  const venues = (await user.call("GET", "/venues/", { expect: 200 })).data;
  const venueId = (venues.results ?? venues)[0].id;
  const detail = (await user.call("GET", `/venues/${venueId}/`, { expect: 200 })).data;
  const sessionId = detail.halls[0].sessions[0].id;
  const { data: booking } = await user.call("POST", "/me/venue-bookings/", {
    body: { session: sessionId, date: inDays(30 + Math.floor(Math.random() * 300)), guest_count: 120 },
    expect: 201,
  });
  const owner = session(PANELS.venue);
  await owner.login("+998901110004");
  const ownerVenues = (await owner.call("GET", "/venue-owner/venues/", { expect: 200 })).data;
  const ownVenueId = (ownerVenues.results ?? ownerVenues)[0].id;
  const confirmed = await owner.call("POST", `/venue-owner/venues/${ownVenueId}/bookings/${booking.id}/confirm/`, {
    expect: 200,
  });
  const mine = (await user.call("GET", `/me/venue-bookings/${booking.id}/`, { expect: 200 })).data;
  assert.equal(mine.status, confirmed.data.status);
  console.log(`booking request -> owner confirm: passed (status ${mine.status})`);
}

// 5) Super Admin storage status reports configuration instead of pretending Drive works.
{
  const sa = session(PANELS.admin);
  await sa.login("+998901110001");
  const { data } = await sa.call("GET", "/admin/storage/google/status/", { expect: 200 });
  console.log(`google drive status: has_credential=${data.has_credential} connection=${data.connection.status}`);
}

console.log(`${results.length} workflow HTTP checks passed`);
