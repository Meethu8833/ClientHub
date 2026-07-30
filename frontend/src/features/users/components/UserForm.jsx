import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "../../../components/ui/Button";
import { Checkbox } from "../../../components/ui/Checkbox";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import { Spinner } from "../../../components/ui/Spinner";
import { ROLE_LABELS, ROLE_OPTIONS, ROLES } from "../../../lib/constants";
import { applyServerErrors, EMAIL_PATTERN } from "../../../lib/forms";
import { useUser } from "../hooks/useUser";
import { useUserMutations } from "../hooks/useUserMutations";

// Mirrors Django's MinimumLengthValidator (settings base.py). The server runs
// the full validator set (similarity, common-password, numeric) on submit —
// this only catches the obvious cases before a round-trip.
const PASSWORD_MIN_LENGTH = 8;

// Every field the two modes render. A 400 on one of these lands on its input;
// anything else (e.g. "detail") becomes the root banner.
const FIELD_NAMES = [
  "email",
  "first_name",
  "last_name",
  "role",
  "password",
  "weekly_capacity_hours",
];

function toFormValues(user) {
  return {
    email: user?.email ?? "",
    first_name: user?.first_name ?? "",
    last_name: user?.last_name ?? "",
    // New teammates default to the least-privileged role — promoting later is
    // one click, while an accidental admin is a security problem.
    role: user?.role ?? ROLES.STAFF,
    weekly_capacity_hours: user?.weekly_capacity_hours ?? "40.0",
    set_password: true,
    password: "",
  };
}

// Create + edit in one component (archetype D). `user` null → create a
// teammate, a table row → edit that one.
//
// The two modes edit deliberately different fields, because the API splits
// them: POST takes email/names/role/password, PATCH takes names + capacity
// only. Email is the login identifier (changing it needs re-verification) and
// role has its own audited endpoint — so on edit both render read-only, with
// the role change pointed at the "Change role" action.
export function UserForm({ isOpen, onClose, user = null }) {
  const isEdit = user != null;
  const { create, update } = useUserMutations();
  const mutation = isEdit ? update : create;

  // Rows come from the slim list serializer; edit needs the full record.
  const { data: detail } = useUser(user?.id, { enabled: isOpen && isEdit });
  const record = isEdit ? detail : null;

  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch,
    formState: { errors },
  } = useForm({
    defaultValues: toFormValues(null),
    // Validate on first blur, then per keystroke — mistakes surface while
    // typing rather than after submit.
    mode: "onTouched",
  });

  // Re-arm the form each time the modal opens, so a previous open's values
  // never leak into a fresh create. On edit this waits for the detail fetch —
  // filling the inputs from the slim row would blank the fields it lacks.
  useEffect(() => {
    if (isOpen && (!isEdit || record)) reset(toFormValues(record));
  }, [isOpen, isEdit, record, reset]);

  const setPassword = watch("set_password");
  const email = watch("email");

  function onSubmit(values) {
    const payload = isEdit
      ? {
          id: user.id,
          first_name: values.first_name.trim(),
          last_name: values.last_name.trim(),
          weekly_capacity_hours: values.weekly_capacity_hours,
        }
      : {
          // The server lowercases and uniqueness-checks case-insensitively;
          // normalizing here keeps what we send equal to what gets stored.
          email: values.email.trim().toLowerCase(),
          first_name: values.first_name.trim(),
          last_name: values.last_name.trim(),
          role: values.role,
          // Omitting `password` entirely is the invite flow — do NOT send an
          // empty string, which the serializer would try to validate.
          ...(values.set_password ? { password: values.password } : {}),
        };

    mutation.mutate(payload, {
      onSuccess: () => onClose(),
      onError: (error) => applyServerErrors(error, setError, FIELD_NAMES),
    });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `Edit ${user.full_name || user.email}` : "New user"}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="user-form"
            isLoading={mutation.isPending}
            disabled={isEdit && !record}
          >
            {isEdit ? "Save changes" : "Create user"}
          </Button>
        </>
      }
    >
      {isEdit && !record ? (
        <div className="flex justify-center py-10">
          <Spinner size="lg" className="text-indigo-600" />
        </div>
      ) : (
        /* The submit button lives in the modal footer, outside <form> — the
         id + form="" attribute pair connects them. */
        <form id="user-form" onSubmit={handleSubmit(onSubmit)} noValidate>
          {errors.root && (
            <p
              role="alert"
              className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700
              dark:bg-red-500/10 dark:text-red-300"
            >
              {errors.root.message}
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {isEdit ? (
              <Input
                label="Email"
                value={record.email}
                readOnly
                disabled
                hint="The login identifier — it cannot be changed here."
                className="sm:col-span-2"
              />
            ) : (
              <Input
                label="Email *"
                type="email"
                autoComplete="off"
                hint="This is what they sign in with."
                className="sm:col-span-2"
                error={errors.email?.message}
                {...register("email", {
                  required: "Email is required.",
                  validate: (v) => EMAIL_PATTERN.test(v.trim()) || "Enter a valid email address.",
                })}
              />
            )}

            <Input
              label="First name"
              autoComplete="off"
              error={errors.first_name?.message}
              {...register("first_name")}
            />
            <Input
              label="Last name"
              autoComplete="off"
              error={errors.last_name?.message}
              {...register("last_name")}
            />

            {isEdit ? (
              <>
                <Input
                  label="Role"
                  value={ROLE_LABELS[record.role] ?? record.role}
                  readOnly
                  disabled
                  hint="Use the row's “Change role” action — role changes are audited separately."
                />
                <Input
                  label="Weekly capacity (hours)"
                  type="number"
                  step="0.5"
                  min="0"
                  max="80"
                  hint="Contracted hours per week — the basis for capacity planning."
                  error={errors.weekly_capacity_hours?.message}
                  {...register("weekly_capacity_hours", {
                    validate: (v) => {
                      const hours = Number(v);
                      if (Number.isNaN(hours)) return "Enter a number of hours.";
                      return (hours >= 0 && hours <= 80) || "Enter between 0 and 80 hours.";
                    },
                  })}
                />
              </>
            ) : (
              <Select
                label="Role"
                options={ROLE_OPTIONS}
                hint="Staff read; managers also write. Admins additionally manage users."
                className="sm:col-span-2"
                error={errors.role?.message}
                {...register("role")}
              />
            )}
          </div>

          {/* Password block — create only. Two supported flows, and the choice
            has consequences the admin should see before saving. */}
          {!isEdit && (
            <div className="mt-5 border-t border-gray-200 pt-5 dark:border-gray-800">
              <Checkbox
                label="Set a password now"
                hint={
                  setPassword
                    ? "You will have to pass this password on to them yourself."
                    : `ClientHub emails ${email?.trim() || "them"} a link to choose their own password.`
                }
                {...register("set_password")}
              />

              {setPassword && (
                <Input
                  label="Password *"
                  type="password"
                  autoComplete="new-password"
                  className="mt-4 sm:w-1/2"
                  hint={`At least ${PASSWORD_MIN_LENGTH} characters, not a common one.`}
                  error={errors.password?.message}
                  {...register("password", {
                    // Only required while the checkbox is on — an unchecked box
                    // means the field isn't rendered and isn't submitted.
                    validate: (value, values) => {
                      if (!values.set_password) return true;
                      if (!value) return "Password is required.";
                      if (value.length < PASSWORD_MIN_LENGTH) {
                        return `Use at least ${PASSWORD_MIN_LENGTH} characters.`;
                      }
                      return !/^\d+$/.test(value) || "A password cannot be entirely numeric.";
                    },
                  })}
                />
              )}
            </div>
          )}
        </form>
      )}
    </Modal>
  );
}
