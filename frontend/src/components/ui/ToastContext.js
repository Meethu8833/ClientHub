import { createContext } from "react";

// Context object alone in its own file (same split as features/auth): files
// that export only components keep Vite fast-refresh working.
export const ToastContext = createContext(null);
