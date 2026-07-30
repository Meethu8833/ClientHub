import { createContext } from "react";

// Split from the provider so this module exports only a constant — a file that
// exports both a context and a component breaks react-refresh's fast reload
// (the same reason AuthContext.js is separate from AuthProvider.jsx).
export const ThemeContext = createContext(null);
