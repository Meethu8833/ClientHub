import { Spinner } from "./Spinner";

const VARIANTS = {
  primary:
    "bg-indigo-600 text-white shadow-sm hover:bg-indigo-500 dark:bg-indigo-600 dark:hover:bg-indigo-500",
  secondary:
    "bg-white text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 " +
    "dark:bg-gray-800 dark:text-gray-100 dark:ring-gray-600 dark:hover:bg-gray-700",
  // red-600 is chosen for contrast on white; on a dark surface the same fill
  // glares, so dark steps down to red-700 with a lighter hover.
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-500 dark:bg-red-700 dark:hover:bg-red-600",
  ghost: "text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800",
};

export function Button({
  variant = "primary",
  type = "button", // explicit: a bare <button> inside a <form> submits it
  isLoading = false,
  disabled = false,
  className = "",
  children,
  ...rest
}) {
  return (
    <button
      type={type}
      disabled={disabled || isLoading}
      className={`inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm
        font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2
        focus-visible:outline-indigo-600 disabled:cursor-not-allowed disabled:opacity-60
        ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {isLoading && <Spinner size="sm" />}
      {children}
    </button>
  );
}
