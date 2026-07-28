import { useCallback, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { ToastContext } from "./ToastContext";

// App-wide toasts (design doc §4.1): top-right stack, 4 s auto-dismiss,
// aria-live="polite" so screen readers announce without interrupting.
// Context (not a global singleton) so tests can mount their own provider.
// The context object and useToast live in sibling files (fast-refresh rule).

const TONES = {
  success: "bg-green-600",
  error: "bg-red-600",
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (tone, message) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { id, tone, message }]);
      setTimeout(() => dismiss(id), 4000);
    },
    [dismiss]
  );

  // Stable object so consumers' effects don't re-run on every render.
  const toast = useMemo(
    () => ({
      success: (message) => push("success", message),
      error: (message) => push("error", message),
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {createPortal(
        <div
          aria-live="polite"
          className="pointer-events-none fixed right-4 top-4 z-[60] flex w-80 flex-col gap-2"
        >
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`pointer-events-auto flex items-start justify-between gap-3 rounded-lg
                px-4 py-3 text-sm text-white shadow-md ${TONES[t.tone]}`}
            >
              <p>{t.message}</p>
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => dismiss(t.id)}
                className="shrink-0 rounded text-white/80 hover:text-white"
              >
                <svg
                  aria-hidden="true"
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
    </ToastContext.Provider>
  );
}
