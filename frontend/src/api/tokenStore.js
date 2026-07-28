// The access token lives in a plain module variable — JS memory only, per
// ARCHITECTURE §7. Never localStorage/sessionStorage (readable by any XSS).
// It dies on refresh (F5); AuthProvider restores it via the silent refresh.
// A separate module so both client.js and AuthProvider can use it without
// importing each other (avoids a circular import).
let accessToken = null;

export function getAccessToken() {
  return accessToken;
}

export function setAccessToken(token) {
  accessToken = token;
}
