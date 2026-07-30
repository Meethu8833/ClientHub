import { useEffect, useRef, useState } from "react";

// Debounced search box (design doc §4.1). Typing fires onDebouncedChange only
// after the user pauses 400 ms — otherwise every keystroke would become an
// API request AND a history entry (filters live in the URL).
//
// `value` is the *committed* value from the URL; local state holds what's
// being typed. The effect syncs URL → box (back button, "Clear filters"),
// but only when the box isn't mid-edit, so we never fight the user's typing.
export function SearchInput({ value, onDebouncedChange, placeholder = "Search…", className = "" }) {
  const [text, setText] = useState(value);
  const timer = useRef(null);

  useEffect(() => {
    setText(value);
  }, [value]);

  function handleChange(e) {
    const next = e.target.value;
    setText(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => onDebouncedChange(next), 400);
  }

  function clear() {
    clearTimeout(timer.current);
    setText("");
    onDebouncedChange(""); // clearing should feel instant — no debounce
  }

  useEffect(() => () => clearTimeout(timer.current), []); // no timer past unmount

  return (
    <div className={`relative ${className}`}>
      <svg
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400
          dark:text-gray-500"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="m21 21-4.35-4.35M17 10.5a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z"
        />
      </svg>
      <input
        type="search"
        role="searchbox"
        aria-label={placeholder}
        value={text}
        onChange={handleChange}
        placeholder={placeholder}
        className="block w-full rounded-md border-0 py-2 pl-9 pr-8 text-gray-900 shadow-sm
          ring-1 ring-inset ring-gray-300 placeholder:text-gray-400
          focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-sm
          dark:bg-gray-800 dark:text-gray-100 dark:ring-gray-600
          dark:placeholder:text-gray-500 dark:focus:ring-indigo-400"
      />
      {text && (
        <button
          type="button"
          aria-label="Clear search"
          onClick={clear}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400
            hover:text-gray-600 dark:hover:text-gray-200"
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
      )}
    </div>
  );
}
