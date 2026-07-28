import { createContext } from "react";

// The context object lives in its own file so AuthProvider.jsx exports only
// a component (keeps React Fast Refresh happy) and useAuth.js only a hook.
export const AuthContext = createContext(null);
