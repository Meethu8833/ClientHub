import { forwardRef, useId } from "react";

// Checkbox with its label inline (design doc §4.1). The hint line is where
// consequences live ("this replaces the current primary contact").
export const Checkbox = forwardRef(function Checkbox(
  { label, hint, className = "", ...rest },
  ref
) {
  const id = useId();

  return (
    <div className={className}>
      <div className="flex items-center gap-2">
        <input
          ref={ref}
          id={id}
          type="checkbox"
          className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-600"
          {...rest}
        />
        <label htmlFor={id} className="text-sm font-medium text-gray-700">
          {label}
        </label>
      </div>
      {hint && <p className="mt-1 pl-6 text-xs text-gray-500">{hint}</p>}
    </div>
  );
});
