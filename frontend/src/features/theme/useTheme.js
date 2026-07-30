import { useContext } from "react";

import { ThemeContext } from "./ThemeContext";

// The only way components read or change the theme. Throwing on a missing
// provider turns a silent "undefined theme" bug into a loud, obvious error
// (same contract as useAuth).
export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used inside <ThemeProvider>");
  return ctx;
}
