import { useState } from "react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { useAuth } from "./useAuth";

// Map an axios error to something a human can act on. The backend deliberately
// returns the same 401 for wrong email and wrong password (no user enumeration).
function loginErrorMessage(err) {
  const status = err.response?.status;
  if (status === 401) return "Invalid email or password.";
  if (status === 429) return "Too many attempts — please wait a minute and try again.";
  if (!err.response) return "Cannot reach the server. Is the backend running?";
  return err.response.data?.detail || "Something went wrong. Please try again.";
}

export function LoginPage() {
  const { user, isBooting, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [serverError, setServerError] = useState(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm();

  // Where ProtectedRoute said the user was originally headed.
  const from = location.state?.from?.pathname || "/";

  if (isBooting) return null; // silent refresh may log us in — don't flash the form
  if (user) return <Navigate to={from} replace />; // already logged in

  async function onSubmit(values) {
    setServerError(null);
    try {
      await login(values.email, values.password);
      navigate(from, { replace: true });
    } catch (err) {
      setServerError(loginErrorMessage(err));
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-center text-2xl font-bold text-indigo-900">
          Client<span className="text-indigo-400">Hub</span>
        </h1>
        <p className="mt-1 text-center text-sm text-gray-500">Sign in to your account</p>

        <form
          onSubmit={handleSubmit(onSubmit)}
          noValidate
          className="mt-8 space-y-4 rounded-lg bg-white p-6 shadow"
        >
          {serverError && (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700" role="alert">
              {serverError}
            </div>
          )}

          <Input
            label="Email"
            type="email"
            autoComplete="email"
            placeholder="you@company.com"
            error={errors.email?.message}
            {...register("email", {
              required: "Email is required.",
              pattern: { value: /^\S+@\S+\.\S+$/, message: "Enter a valid email address." },
            })}
          />

          <Input
            label="Password"
            type="password"
            autoComplete="current-password"
            error={errors.password?.message}
            {...register("password", { required: "Password is required." })}
          />

          <Button type="submit" isLoading={isSubmitting} className="w-full">
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
