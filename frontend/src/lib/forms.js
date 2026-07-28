// Shape checks shared by the client and contact forms, for instant feedback
// while typing. The server stays authoritative on submit.
// PHONE_PATTERN mirrors clients.models.PHONE_VALIDATOR exactly: optional "+"
// then 7–15 digits, up to two space/dash/bracket separators between digits.
export const PHONE_PATTERN = /^\+?[0-9](?:[ \-()]{0,2}[0-9]){6,14}$/;
export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Maps a DRF 400 body onto react-hook-form fields (ARCHITECTURE §11:
// "API validation errors mapped back onto fields").
//
// DRF's shape: {"field_name": ["msg", ...]} for field errors,
// {"detail": "msg"} or {"non_field_errors": [...]} for record-level ones.
// Anything that doesn't match a rendered field becomes a "root" error the
// form shows as a banner — a message the user can't see is a bug.
export function applyServerErrors(error, setError, fieldNames) {
  const data = error?.response?.data;
  if (!data || typeof data !== "object") {
    setError("root", { message: "Something went wrong. Please try again." });
    return;
  }

  for (const [field, messages] of Object.entries(data)) {
    const message = Array.isArray(messages) ? messages[0] : String(messages);
    if (fieldNames.includes(field)) {
      setError(field, { type: "server", message });
    } else {
      setError("root", { message });
    }
  }
}

// Wraps an async react-hook-form validator so one-call-per-keystroke
// collapses into a single request after `ms` of quiet. Superseded and failed
// runs resolve `true` (pass): the newest run owns the verdict, and a network
// hiccup must never trap the user in an error they can't clear — the server
// re-validates on submit anyway.
export function debouncePromise(fn, ms = 400) {
  let timer = null;
  let resolveSuperseded = null;
  return (...args) =>
    new Promise((resolve) => {
      if (timer) {
        clearTimeout(timer);
        resolveSuperseded(true);
      }
      resolveSuperseded = resolve;
      timer = setTimeout(async () => {
        timer = null;
        try {
          resolve(await fn(...args));
        } catch {
          resolve(true);
        }
      }, ms);
    });
}
