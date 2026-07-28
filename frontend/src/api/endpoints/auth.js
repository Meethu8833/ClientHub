import { api } from "../client";

// One file per backend app (ARCHITECTURE §3). Components never call axios
// directly — they go through these named functions, so the URL strings and
// payload shapes live in exactly one place.

export async function login(email, password) {
  const { data } = await api.post("/auth/login/", { email, password });
  return data; // { access, user } + Set-Cookie: refresh_token (HttpOnly)
}

export async function fetchMe() {
  const { data } = await api.get("/auth/me/");
  return data; // the user object
}

export async function logout() {
  await api.post("/auth/logout/"); // blacklists the refresh token, clears cookie
}
