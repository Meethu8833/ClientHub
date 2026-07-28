import { forwardRef, useEffect, useId, useRef, useState } from "react";

// A text input with a styled suggestion dropdown — the app-controlled
// replacement for a native <datalist>, whose popup browsers don't let us
// style or position. The field stays free text: suggestions are offered,
// never enforced.
//
// Works with react-hook-form's register() spread (name/ref/onChange/onBlur
// pass straight through to the <input>). Picking a suggestion calls
// `onSelect(value)` — the parent owns the form state, so it writes the value
// (e.g. RHF setValue) rather than this component reaching into the form.
//
// Layout: the list is absolutely positioned under the input and w-full, so
// it always matches the input's width at any viewport size, and it scrolls
// internally past ~8 visible rows.
export const AutocompleteInput = forwardRef(function AutocompleteInput(
  {
    label,
    error,
    hint,
    suggestions = [],
    onSelect,
    className = "",
    onChange,
    onBlur,
    ...rest
  },
  ref
) {
  const id = useId();
  const listboxId = useId();
  const rootRef = useRef(null);
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState(""); // what's been typed since open — filters the list
  const [highlighted, setHighlighted] = useState(-1); // keyboard cursor, -1 = nothing

  const q = query.trim().toLowerCase();
  const matches = q ? suggestions.filter((s) => s.toLowerCase().includes(q)) : suggestions;
  const showList = isOpen && matches.length > 0;

  // Close when a click/tap lands outside the component (mobile included).
  useEffect(() => {
    if (!isOpen) return;
    function onDocPointerDown(e) {
      if (!rootRef.current?.contains(e.target)) setIsOpen(false);
    }
    document.addEventListener("pointerdown", onDocPointerDown);
    return () => document.removeEventListener("pointerdown", onDocPointerDown);
  }, [isOpen]);

  function choose(value) {
    onSelect?.(value);
    setIsOpen(false);
    setQuery(""); // next open starts from the full list again
    setHighlighted(-1);
  }

  function handleKeyDown(e) {
    if (e.key === "Escape") {
      setIsOpen(false);
      return;
    }
    if (!showList) {
      // Arrow down on a closed field opens the list — standard combobox feel.
      if (e.key === "ArrowDown" && matches.length > 0) {
        e.preventDefault();
        setIsOpen(true);
      }
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlighted((h) => (h + 1) % matches.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlighted((h) => (h <= 0 ? matches.length - 1 : h - 1));
    } else if (e.key === "Enter" && highlighted >= 0 && highlighted < matches.length) {
      // Only intercept Enter while an option is highlighted — otherwise it
      // must keep submitting the form as usual.
      e.preventDefault();
      choose(matches[highlighted]);
    }
  }

  return (
    <div ref={rootRef} className={`relative ${className}`}>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        type="text"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listboxId}
        aria-autocomplete="list"
        autoComplete="off"
        aria-invalid={error ? "true" : undefined}
        className={`mt-1 block w-full rounded-md border-0 px-3 py-2 text-gray-900 shadow-sm
          ring-1 ring-inset placeholder:text-gray-400 focus:ring-2 focus:ring-inset sm:text-sm
          ${error ? "ring-red-400 focus:ring-red-500" : "ring-gray-300 focus:ring-indigo-600"}`}
        onFocus={() => setIsOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setIsOpen(true);
          setHighlighted(-1);
          onChange?.(e); // keep react-hook-form's handler in the loop
        }}
        onBlur={onBlur}
        onKeyDown={handleKeyDown}
        {...rest}
      />
      {showList && (
        <ul
          id={listboxId}
          role="listbox"
          // max-h = 8 rows; w-full pins the list to the input's width so it
          // tracks the field across breakpoints instead of overflowing small
          // screens.
          className="absolute z-10 mt-1 max-h-72 w-full overflow-auto rounded-md bg-white py-1
            text-sm shadow-lg ring-1 ring-gray-200"
        >
          {matches.map((option, i) => (
            <li
              key={option}
              role="option"
              aria-selected={i === highlighted}
              // preventDefault keeps focus (and RHF's touched state) on the
              // input — otherwise blur fires before click and eats the tap.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => choose(option)}
              onMouseEnter={() => setHighlighted(i)}
              className={`cursor-pointer px-3 py-2 ${
                i === highlighted ? "bg-indigo-600 text-white" : "text-gray-900"
              }`}
            >
              {option}
            </li>
          ))}
        </ul>
      )}
      {hint && !error && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
      {error && (
        <p className="mt-1 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});
