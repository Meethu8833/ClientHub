// Theme preference: the pure logic, with no React in it.
//
// Shared by the provider AND by the inline boot script in index.html, which
// runs before any bundle loads — so the rules for "what does this preference
// resolve to" live in exactly one place conceptually. (The boot script inlines
// a minimal copy for speed; keep STORAGE_KEY and the class name in sync.)

export const THEMES = { LIGHT: "light", DARK: "dark", SYSTEM: "system" };

// Not a security-sensitive value, so localStorage is fine here — unlike auth
// tokens, which ARCHITECTURE §7 deliberately keeps in memory only.
export const STORAGE_KEY = "clienthub-theme";

// The cycle order the toggle button walks through.
export const THEME_ORDER = [THEMES.LIGHT, THEMES.DARK, THEMES.SYSTEM];

export function readStoredTheme() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === THEMES.LIGHT || v === THEMES.DARK || v === THEMES.SYSTEM ? v : THEMES.SYSTEM;
  } catch {
    // Private mode / storage disabled — fall back to following the OS.
    return THEMES.SYSTEM;
  }
}

export function storeTheme(theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Non-fatal: the theme still applies for this session.
  }
}

export function systemPrefersDark() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}

// preference → the theme actually painted ("system" is not a look, it is a
// rule for picking one).
export function resolveTheme(preference) {
  if (preference === THEMES.SYSTEM) return systemPrefersDark() ? THEMES.DARK : THEMES.LIGHT;
  return preference;
}

// The single place the class is written. `.dark` is what the `dark:` variant
// keys off (see styles/index.css).
export function applyTheme(preference) {
  const resolved = resolveTheme(preference);
  document.documentElement.classList.toggle("dark", resolved === THEMES.DARK);
  return resolved;
}
