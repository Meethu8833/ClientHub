import { useContext } from "react";

import { ToastContext } from "./ToastContext";

// The only way components fire toasts. Throwing on a missing provider turns
// a silent "nothing appeared" bug into a loud, obvious error.
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
