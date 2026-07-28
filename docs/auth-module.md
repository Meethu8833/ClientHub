# ClientHub — Authentication & Authorization Module

Phase 1 of the roadmap. Backend lives in `backend/apps/accounts/` (+ role
permission classes in `backend/apps/core/permissions.py`). Token contract
(ARCHITECTURE.md §7): **access token** (15 min) in the response body, kept in
React memory; **refresh token** (7 days) in an `HttpOnly` cookie scoped to
`/api/v1/auth/`, rotated and blacklisted on every refresh.

All URLs below are relative to `http://localhost:8000/api/v1/auth/`.

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `login/` | POST | — | email+password → access token + refresh cookie |
| `refresh/` | POST | refresh cookie | new access token, rotated cookie |
| `logout/` | POST | refresh cookie | blacklist refresh, clear cookie |
| `me/` | GET / PATCH | Bearer | read / update own profile |
| `change-password/` | POST | Bearer | change password (knows current one) |
| `forgot-password/` | POST | — | email a reset link (never reveals existence) |
| `reset-password/` | POST | — | consume link, set new password |
| `send-verification-email/` | POST | Bearer | (re)send verification link |
| `verify-email/` | POST | — | consume link, mark email verified |

Throttles: `login` 10/min, `password_reset` 5/hour, `email_verification`
5/hour, everything else the global anon/user rates.

---

## Postman walkthrough

Postman stores cookies per-domain automatically, so it behaves like the
browser: after login, the refresh cookie is attached to later `/auth/*` calls
without you doing anything. Watch it under **Cookies** (below the Send button).

Prereq: a user to log in with. Create one from the backend directory:

```bash
.venv/bin/python manage.py createsuperuser  # asks email + password only
```

### 1. Login

`POST http://localhost:8000/api/v1/auth/login/` — Body → raw → JSON:

```json
{ "email": "ana@example.com", "password": "Str0ng!pass123" }
```

`200 OK`:

```json
{
  "access": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": 1,
    "email": "ana@example.com",
    "first_name": "Ana",
    "last_name": "",
    "role": "staff",
    "is_email_verified": false,
    "date_joined": "2026-07-25T09:12:00Z",
    "last_login": "2026-07-25T09:30:41Z"
  }
}
```

Response headers include
`Set-Cookie: refresh_token=eyJ...; HttpOnly; Path=/api/v1/auth/; SameSite=Lax`.

Wrong password / unknown email — identical `401`:

```json
{ "detail": "No active account found with the given credentials" }
```

### 2. Call a protected endpoint

`GET .../auth/me/` with header `Authorization: Bearer <access>` → `200` with
the same user object. Without the header → `401 {"detail": "Authentication
credentials were not provided."}`.

Tip: put the access token in a Postman environment variable (`{{access}}`)
and set the header once at collection level.

### 3. Refresh

`POST .../auth/refresh/` — **empty body**; Postman sends the cookie itself.

`200 OK`: `{ "access": "eyJ...new..." }` + a **new** rotated refresh cookie.
Replaying the *old* cookie afterwards → `401` (blacklisted).

### 4. Update profile

`PATCH .../auth/me/` (Bearer) `{ "first_name": "Anna" }` → `200`. Sending
`"role": "admin"` is silently ignored — read-only field.

### 5. Change password

`POST .../auth/change-password/` (Bearer):

```json
{ "current_password": "Str0ng!pass123", "new_password": "N3w!password456" }
```

`200 {"detail": "Password changed."}` — all other devices' refresh tokens are
revoked; this device gets a fresh cookie. Wrong current password → `400
{"current_password": ["Current password is incorrect."]}`. Weak new password →
`400 {"new_password": ["This password is too short..."]}`.

### 6. Forgot / reset password

`POST .../auth/forgot-password/` `{ "email": "ana@example.com" }` → always
`200 {"detail": "If an account with that email exists, a reset link has been
sent."}` — same body whether or not the account exists.

In dev the email prints in the `runserver` console. Copy `uid` and `token`
from the link (`.../reset-password?uid=MQ&token=cq3xyz-...`), then:

`POST .../auth/reset-password/`:

```json
{ "uid": "MQ", "token": "cq3xyz-...", "new_password": "N3w!password456" }
```

`200` → log in with the new password. Reusing the link → `400` (single-use).
Links expire after 1 hour (`PASSWORD_RESET_TIMEOUT`).

### 7. Email verification

1. `POST .../auth/send-verification-email/` (Bearer) → `200`, link printed to
   console.
2. `POST .../auth/verify-email/` `{ "token": "<from link>" }` (no auth needed —
   the signed token proves identity) → `200 {"detail": "Email verified."}`.
   Tampered/expired token → `400`. Links expire after 24 h
   (`EMAIL_VERIFICATION_TIMEOUT`).

### 8. Logout

`POST .../auth/logout/` → `200 {"detail": "Logged out."}`; cookie cleared,
refresh token blacklisted. A later `refresh/` → `401`.

---

## How React consumes this (Phase 1 frontend)

Three pieces (see ARCHITECTURE.md §3/§7): an axios instance with
interceptors, an `AuthProvider` context, and `ProtectedRoute`/`RoleGate`.

**`api/client.js`** — the axios instance:

```js
import axios from "axios";

export const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true, // ← send/receive the HttpOnly refresh cookie
});

let accessToken = null; // module-scoped memory — never localStorage
export const setAccessToken = (t) => { accessToken = t; };

api.interceptors.request.use((config) => {
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  return config;
});

// On 401: refresh ONCE (concurrent 401s share the same promise), then replay.
let refreshing = null;
api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retried) {
      original._retried = true;
      refreshing ??= api
        .post("/auth/refresh/")
        .then((r) => setAccessToken(r.data.access))
        .finally(() => { refreshing = null; });
      try {
        await refreshing;
        return api(original); // replay with the new access token
      } catch {
        setAccessToken(null);
        window.location.assign("/login"); // refresh dead → real logout
      }
    }
    return Promise.reject(error);
  }
);
```

**`features/auth/AuthProvider.jsx`** — boot + login/logout:

```js
// On mount: try a silent refresh. If the HttpOnly cookie is still valid,
// the session survives F5 without showing the login page.
useEffect(() => {
  api.post("/auth/refresh/")
    .then((r) => { setAccessToken(r.data.access); return api.get("/auth/me/"); })
    .then((r) => setUser(r.data))
    .catch(() => setUser(null))
    .finally(() => setBooting(false));
}, []);

const login = async (email, password) => {
  const { data } = await api.post("/auth/login/", { email, password });
  setAccessToken(data.access);
  setUser(data.user); // login already returns the profile — no second call
};

const logout = async () => {
  await api.post("/auth/logout/");
  setAccessToken(null);
  setUser(null);
};
```

**Route guards** — UX only; the server re-checks everything:

```js
const ProtectedRoute = () => {
  const { user, booting } = useAuth();
  if (booting) return <Spinner />;
  return user ? <Outlet /> : <Navigate to="/login" replace />;
};

const RoleGate = ({ allow, children }) =>
  useAuth().user && allow.includes(useAuth().user.role) ? children : null;
```

Email-link pages: `/reset-password` reads `?uid=&token=` with
`useSearchParams`, shows a new-password form, POSTs `reset-password/`, then
redirects to `/login`. `/verify-email` POSTs its `?token=` on mount and shows
the result.

**Storage rules:** access token in a JS variable (dies on refresh — restored
by silent refresh), refresh token in the HttpOnly cookie (browser-managed),
**nothing in localStorage** — anything there is readable by any injected
script (XSS).

---

## Security decisions baked in

- **No user enumeration** — login, forgot-password give identical responses
  for unknown emails; wrong-password and unknown-email are indistinguishable.
- **Refresh rotation + blacklist** — a stolen refresh token dies the moment
  either party refreshes; logout and password change/reset blacklist
  explicitly (`revoke_all_refresh_tokens`).
- **HttpOnly + Path-scoped + SameSite=Lax cookie** — XSS can't read it, it is
  only ever sent to `/api/v1/auth/*`, and cross-site POSTs don't carry it.
  `Secure` flag on everywhere except dev.
- **Password policy** — Django's `AUTH_PASSWORD_VALIDATORS` run on change and
  reset; hashes are PBKDF2 (never plaintext, never reversible).
- **Single-use reset links** — Django's token embeds the password hash +
  last-login timestamp, so using the link (or logging in) invalidates it.
- **Signed verification tokens** — `django.core.signing` with a dedicated
  salt and 24 h `max_age`; tampering breaks the signature.
- **Throttling** — login 10/min, reset/verification emails 5/hour per caller.
- **Generic server-side errors** — serializer messages never leak internals.
