import { useCallback, useEffect, useMemo, useState } from "react";

import { ThemeContext } from "./ThemeContext";
import {
  applyTheme,
  readStoredTheme,
  resolveTheme,
  storeTheme,
  THEME_ORDER,
  THEMES,
} from "./theme";

export function ThemeProvider({ children }) {
  // Initialised from storage (not from a hardcoded default) so the very first
  // render already agrees with the class the boot script put on <html> — no
  // flash, no mismatch.
  const [preference, setPreference] = useState(readStoredTheme);
  const [resolved, setResolved] = useState(() => resolveTheme(readStoredTheme()));

  useEffect(() => {
    setResolved(applyTheme(preference));
    storeTheme(preference);
  }, [preference]);

  // While on "System", follow the OS if the user flips it mid-session. The
  // listener is only meaningful for that preference, hence the early return.
  useEffect(() => {
    if (preference !== THEMES.SYSTEM) return;

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setResolved(applyTheme(THEMES.SYSTEM));
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  const setTheme = useCallback((next) => setPreference(next), []);

  const cycleTheme = useCallback(() => {
    setPreference((prev) => {
      const i = THEME_ORDER.indexOf(prev);
      return THEME_ORDER[(i + 1) % THEME_ORDER.length];
    });
  }, []);

  // useMemo keeps the context value referentially stable, so consumers only
  // re-render when the theme actually changes (same idiom as AuthProvider).
  const value = useMemo(
    () => ({ preference, resolved, isDark: resolved === THEMES.DARK, setTheme, cycleTheme }),
    [preference, resolved, setTheme, cycleTheme]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
