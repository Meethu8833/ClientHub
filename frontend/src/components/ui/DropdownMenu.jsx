import { useEffect, useRef, useState } from "react";

// Row "⋯" actions menu (design doc §4.1). Native <button>s in a popover:
// closes on Esc / click-outside / selection; ArrowUp/Down move between items
// (a11y floor §3.3 — every interaction must work without a mouse).
export function DropdownMenu({ label = "Actions", items }) {
  const [isOpen, setIsOpen] = useState(false);
  const rootRef = useRef(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;

    function handleOutside(e) {
      if (!rootRef.current?.contains(e.target)) setIsOpen(false);
    }
    function handleKeyDown(e) {
      if (e.key === "Escape") {
        setIsOpen(false);
        return;
      }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const options = [...(menuRef.current?.querySelectorAll("[role=menuitem]") ?? [])];
      if (!options.length) return;
      const index = options.indexOf(document.activeElement);
      const next =
        e.key === "ArrowDown"
          ? options[(index + 1) % options.length]
          : options[(index - 1 + options.length) % options.length];
      next.focus();
    }

    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleKeyDown);
    menuRef.current?.querySelector("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={(e) => {
          e.stopPropagation(); // don't trigger the row's onRowClick
          setIsOpen((open) => !open);
        }}
        className="rounded p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600
          focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
      >
        <svg aria-hidden="true" className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 8a2 2 0 1 1 0-4 2 2 0 0 1 0 4Zm0 6a2 2 0 1 1 0-4 2 2 0 0 1 0 4Zm0 6a2 2 0 1 1 0-4 2 2 0 0 1 0 4Z" />
        </svg>
      </button>

      {isOpen && (
        <div
          ref={menuRef}
          role="menu"
          className="absolute right-0 z-10 mt-1 w-40 rounded-md bg-white py-1 shadow-md
            ring-1 ring-gray-200"
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={(e) => {
                e.stopPropagation();
                setIsOpen(false);
                item.onClick();
              }}
              className={`block w-full px-3 py-2 text-left text-sm hover:bg-gray-50
                focus-visible:bg-gray-50 focus-visible:outline-none
                ${item.tone === "danger" ? "text-red-600" : "text-gray-700"}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
