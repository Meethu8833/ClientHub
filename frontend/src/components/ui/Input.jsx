import { forwardRef, useId } from "react";

// forwardRef is required: react-hook-form's register() attaches a ref to read
// the value — without it the field would silently never register.
export const Input = forwardRef(function Input(
  { label, error, hint, type = "text", className = "", ...rest },
  ref
) {
  const id = useId(); // stable unique id so label htmlFor ↔ input id always match

  return (
    <div className={className}>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700">
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        type={type}
        aria-invalid={error ? "true" : undefined}
        className={`mt-1 block w-full rounded-md border-0 px-3 py-2 text-gray-900 shadow-sm
          ring-1 ring-inset placeholder:text-gray-400 focus:ring-2 focus:ring-inset sm:text-sm
          ${error ? "ring-red-400 focus:ring-red-500" : "ring-gray-300 focus:ring-indigo-600"}`}
        {...rest}
      />
      {hint && !error && <p className="mt-1 text-xs text-gray-500">{hint}</p>}
      {error && (
        <p className="mt-1 text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});
