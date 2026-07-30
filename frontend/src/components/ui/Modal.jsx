import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const SIZES = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" };

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Accessible dialog (design doc §3): portal to <body> (escapes any parent
// overflow/z-index), focus moves in on open and BACK to the trigger on close,
// Tab is trapped inside, Esc and backdrop-click dismiss.
export function Modal({ isOpen, onClose, title, size = "md", children, footer }) {
  const panelRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;

    // Remember who opened us — focus must return there on close, or a
    // keyboard user is dumped at the top of the page (a11y floor §3.3).
    const trigger = document.activeElement;
    const panel = panelRef.current;
    (panel.querySelector(FOCUSABLE) ?? panel).focus();

    function handleKeyDown(e) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      // Trap: Tab past the last control wraps to the first, and vice versa.
      const items = panel.querySelectorAll(FOCUSABLE);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.body.style.overflow = "hidden"; // page behind must not scroll
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
      trigger?.focus?.();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      <div
        className="fixed inset-0 bg-gray-900/50 dark:bg-black/70"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className={`relative w-full ${SIZES[size]} max-h-[90vh] overflow-y-auto rounded-lg
          bg-white p-6 shadow-xl dark:bg-gray-900 dark:ring-1 dark:ring-gray-800`}
      >
        <div className="flex items-start justify-between">
          <h2 className="text-base font-semibold text-gray-900 dark:text-gray-50">{title}</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 focus-visible:outline-2
              focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
          >
            <svg
              aria-hidden="true"
              className="h-5 w-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="mt-4">{children}</div>
        {footer && <div className="mt-6 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>,
    document.body
  );
}
