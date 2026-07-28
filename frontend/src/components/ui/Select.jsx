import { forwardRef, useId } from "react";

// A styled NATIVE <select> (design doc §4.1): keyboard support, mobile
// pickers and screen-reader announcements come free — a div-based custom
// dropdown would have to rebuild all three by hand.
// Same label/error API as Input so forms can treat every field alike.
export const Select = forwardRef(function Select(
  { label, error, hint, options, placeholder, className = "", ...rest },
  ref
) {
  const id = useId();

  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700">
        {label}
      </label>
      <select
        ref={ref}
        id={id}
        aria-invalid={error ? "true" : undefined}
        className={`mt-1 block w-full rounded-md border-0 bg-white px-3 py-2 text-gray-900
          shadow-sm ring-1 ring-inset focus:ring-2 focus:ring-inset sm:text-sm
          ${error ? "ring-red-400 focus:ring-red-500" : "ring-gray-300 focus:ring-indigo-600"}`}
        {...rest}
      >
        {/* value="" so react-hook-form reads "nothing chosen" as empty string */}
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {hint && !error && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
      {error && (
        <p className="mt-1 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});
