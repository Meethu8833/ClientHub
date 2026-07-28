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
