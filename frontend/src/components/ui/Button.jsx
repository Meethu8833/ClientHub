import { Spinner } from "./Spinner";

const VARIANTS = {
  primary: "bg-indigo-600 text-white shadow-sm hover:bg-indigo-500",
  secondary: "bg-white text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-500",
  ghost: "text-gray-700 hover:bg-gray-100",
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
