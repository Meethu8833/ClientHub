import { useContext } from "react";

import { AuthContext } from "./AuthContext";

// The only way components touch auth state. Throwing on a missing provider
// turns a silent "undefined user" bug into a loud, obvious error.
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
