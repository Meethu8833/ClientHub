import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import { checkClientAvailability } from "../../../api/endpoints/clients";
import { AutocompleteInput } from "../../../components/ui/AutocompleteInput";
import { Button } from "../../../components/ui/Button";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import {
  applyServerErrors,
  debouncePromise,
  EMAIL_PATTERN,
  PHONE_PATTERN,
} from "../../../lib/forms";
import {
  CLIENT_STATUS_OPTIONS,
  COUNTRY_DIAL_CODE,
  COUNTRY_OPTIONS,
  PHONE_PREFIX_OPTIONS,
} from "../../../lib/constants";
import { getCitySuggestions } from "../../../lib/cities";
import { useAssignableUsers } from "../hooks/useAssignableUsers";
import { useClientMutations } from "../hooks/useClientMutations";

// Matches the model's GSTIN RegexValidator — same rule client-side so the
// user hears about a typo before a round-trip. The server stays the real
// validator (client checks are UX, never security).
const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

// Light shape check for instant feedback; the server's URLField stays
// authoritative on submit.
const URL_PATTERN = /^https?:\/\/\S+\.\S+/;

// Everything ClientWriteSerializer accepts that this form renders. Server
// 400s for these land on the matching field; anything else becomes the
// root banner. (`phone` is edited as prefix+number locally — its server
// errors are re-landed on the number input in onSubmit's onError.)
const FIELD_NAMES = [
  "name",
  "industry",
  "website",
  "email",
  "phone",
  "gst_number",
  "city",
  "country",
  "status",
  "account_manager_id",
];

// Split a stored phone ("+91 98765 43210") into {prefix, number} for the
// two-part input. Longest dial code wins ("+971…" is UAE, not +9 + "71…").
// Unknown or absent prefix → everything stays in `number`, so an untouched
// edit round-trips without silently rewriting stored data.
function splitPhone(phone) {
  const p = (phone ?? "").trim();
  if (p.startsWith("+")) {
    const code = PHONE_PREFIX_OPTIONS.map((o) => o.value)
      .filter((c) => p.startsWith(c))
      .sort((a, b) => b.length - a.length)[0];
    if (code) {
      return { prefix: code, number: p.slice(code.length).replace(/^[ -]/, "").trim() };
    }
  }
  return { prefix: "", number: p };
}

function toFormValues(client) {
  const { prefix, number } = splitPhone(client?.phone);
  return {
    name: client?.name ?? "",
    industry: client?.industry ?? "",
    website: client?.website ?? "",
    email: client?.email ?? "",
    // The API's single `phone` string is edited as prefix + number; create
    // mode defaults the prefix to match the default country (India).
    phone_prefix: client == null ? "+91" : prefix,
    phone_number: number,
    gst_number: client?.gst_number ?? "",
    city: client?.city ?? "",
    country: client?.country ?? "India",
    status: client?.status ?? "prospect",
    // Reads embed the manager as an object; the write field wants a plain id.
    account_manager_id: client?.account_manager?.id ?? "",
  };
}

// Create + edit in one component (archetype D): `client` null → create,
// object → edit. The mutations (and their cache invalidation + toasts)
// live in useClientMutations — this form only renders, validates and maps.
export function ClientForm({ isOpen, onClose, client = null }) {
  const isEdit = client != null;
  const { create, update } = useClientMutations();
  const mutation = isEdit ? update : create;
  const { data: users } = useAssignableUsers({ enabled: isOpen });

  const {
    register,
    handleSubmit,
    reset,
    setError,
    setValue,
    trigger,
    watch,
    formState: { errors },
  } = useForm({
    defaultValues: toFormValues(client),
    // Instant checks: each field validates on its first blur, then on every
    // keystroke — mistakes surface while typing, not after submit.
    mode: "onTouched",
  });

  // "Prefix follows country": picking a country selects its dial code. Only
  // on real change events (type === "change") — reset/setValue must not fire
  // this, or opening an edit form would overwrite a legacy prefix-less phone.
  useEffect(() => {
    const sub = watch((values, { name, type }) => {
      if (name !== "country" || type !== "change") return;
      const code = COUNTRY_DIAL_CODE[(values.country ?? "").trim().toLowerCase()];
      if (code) {
        setValue("phone_prefix", code, { shouldDirty: true });
        trigger("phone_number"); // number's validity depends on the prefix
      }
    });
    return () => sub.unsubscribe();
  }, [watch, setValue, trigger]);

  // City suggestions follow the selected country — the autocomplete re-renders
  // with the new list whenever Country changes.
  const selectedCountry = watch("country");
  const citySuggestions = getCitySuggestions(selectedCountry);

  // Legacy rows may hold a country typed before the curated list existed —
  // keep it selectable so opening the form doesn't silently blank it.
  const countryOptions = useMemo(() => {
    const current = client?.country;
    return current && !COUNTRY_OPTIONS.some((o) => o.value === current)
      ? [...COUNTRY_OPTIONS, { value: current, label: current }]
      : COUNTRY_OPTIONS;
  }, [client]);

  // Duplicate pre-checks against /clients/check/, debounced so per-keystroke
  // revalidation collapses into one request. One debouncer per field —
  // sharing one would let typing in Name cancel a pending GSTIN check.
  const checkNameFree = useMemo(
    () =>
      debouncePromise(async (name, exclude) => {
        const { name_taken } = await checkClientAvailability({ name, exclude });
        return !name_taken || "A client with this name already exists.";
      }),
    []
  );
  const checkGstinFree = useMemo(
    () =>
      debouncePromise(async (gst_number, exclude) => {
        const { gst_number_taken } = await checkClientAvailability({ gst_number, exclude });
        return !gst_number_taken || "A client with this GSTIN already exists.";
      }),
    []
  );

  // Re-arm the form each time the modal opens: a fresh create form, or the
  // current record's values on edit (stale defaults from a previous open
  // would otherwise leak through).
  useEffect(() => {
    if (isOpen) reset(toFormValues(client));
  }, [isOpen, client, reset]);

  function onSubmit({ phone_prefix, phone_number, ...values }) {
    const number = phone_number.trim();
    const payload = {
      ...values,
      // "" is <Select>'s "nobody chosen"; the API wants an explicit null.
      account_manager_id:
        values.account_manager_id === "" ? null : Number(values.account_manager_id),
      gst_number: values.gst_number.trim().toUpperCase(),
      // Recombine into the API's single string; a prefix with no number is
      // meaningless, so blank number → blank phone.
      phone: number ? [phone_prefix, number].filter(Boolean).join(" ") : "",
    };
    mutation.mutate(isEdit ? { id: client.id, ...payload } : payload, {
      onSuccess: () => onClose(),
      onError: (error) => {
        applyServerErrors(error, setError, FIELD_NAMES);
        // `phone` has no rendered field of its own — re-land its server
        // error on the visible number input.
        const phoneError = error?.response?.data?.phone;
        if (phoneError) {
          setError("phone_number", {
            type: "server",
            message: Array.isArray(phoneError) ? phoneError[0] : String(phoneError),
          });
        }
      },
    });
  }

  const managerOptions =
    users?.map((u) => ({ value: u.id, label: `${u.name} (${u.email})` })) ?? [];

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `Edit ${client.name}` : "New client"}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="client-form" isLoading={mutation.isPending}>
            {isEdit ? "Save changes" : "Create client"}
          </Button>
        </>
      }
    >
      {/* id + the footer button's form="" attribute connect them across the
          modal layout — the submit button lives outside the <form> element. */}
      <form id="client-form" onSubmit={handleSubmit(onSubmit)} noValidate>
        {errors.root && (
          <p role="alert" className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {errors.root.message}
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label="Company name *"
            error={errors.name?.message}
            {...register("name", {
              required: "Company name is required.",
              validate: async (v) => {
                const name = v.trim();
                // Unchanged on edit → nothing to ask the server.
                if (!name || (isEdit && name === client.name)) return true;
                return checkNameFree(name, isEdit ? client.id : undefined);
              },
            })}
          />
          <Input label="Industry" error={errors.industry?.message} {...register("industry")} />
          <Input
            label="Website"
            type="url"
            hint="Include the scheme, e.g. https://acme.com"
            error={errors.website?.message}
            {...register("website", {
              validate: (v) =>
                v.trim() === "" ||
                URL_PATTERN.test(v.trim()) ||
                "Enter a full URL including the scheme, e.g. https://acme.com.",
            })}
          />
          <Input
            label="Email"
            type="email"
            error={errors.email?.message}
            {...register("email", {
              validate: (v) =>
                v.trim() === "" || EMAIL_PATTERN.test(v.trim()) || "Enter a valid email address.",
            })}
          />
          {/* One grid cell, two controls: dial code + national number. The
              code follows the Country field but stays hand-pickable. */}
          <div className="flex gap-2">
            <Select
              label="Code"
              placeholder="—"
              options={PHONE_PREFIX_OPTIONS}
              className="w-24 shrink-0"
              error={errors.phone_prefix?.message}
              {...register("phone_prefix", {
                // Number's validity (total length) depends on the prefix.
                onChange: () => trigger("phone_number"),
              })}
            />
            <Input
              label="Phone"
              className="min-w-0 flex-1"
              error={errors.phone_number?.message}
              {...register("phone_number", {
                validate: (v, values) => {
                  const number = v.trim();
                  if (number === "") return true;
                  // Validate exactly what will be submitted — prefix included.
                  const full = values.phone_prefix ? `${values.phone_prefix} ${number}` : number;
                  if (!PHONE_PATTERN.test(full)) {
                    return "Enter a valid phone number, e.g. 98765 43210.";
                  }
                  return full.length <= 20 || "Phone number is too long (20 characters max).";
                },
              })}
            />
          </div>
          <Input
            label="GSTIN"
            hint="15 characters, e.g. 29ABCDE1234F1Z5 — leave blank if unregistered"
            error={errors.gst_number?.message}
            {...register("gst_number", {
              validate: async (v) => {
                const gstin = v.trim().toUpperCase();
                if (gstin === "") return true;
                if (!GSTIN_PATTERN.test(gstin)) {
                  return "Enter a valid 15-character GSTIN, e.g. 29ABCDE1234F1Z5.";
                }
                if (isEdit && gstin === client.gst_number) return true;
                return checkGstinFree(gstin, isEdit ? client.id : undefined);
              },
            })}
          />
          {/* Country before City: picking the country first scopes the city
              suggestions. The field stays free text — suggestions are offered,
              never enforced — and picking one writes through setValue so
              react-hook-form sees it like typed input. */}
          <Select
            label="Country"
            placeholder="— Not set —"
            options={countryOptions}
            error={errors.country?.message}
            {...register("country")}
          />
          <AutocompleteInput
            label="City"
            suggestions={citySuggestions}
            onSelect={(city) =>
              setValue("city", city, { shouldDirty: true, shouldTouch: true })
            }
            error={errors.city?.message}
            {...register("city")}
          />
          <Select
            label="Status"
            options={CLIENT_STATUS_OPTIONS}
            error={errors.status?.message}
            {...register("status")}
          />
          <Select
            label="Account manager"
            placeholder="— Unassigned —"
            options={managerOptions}
            error={errors.account_manager_id?.message}
            className="sm:col-span-2"
            {...register("account_manager_id")}
          />
        </div>
      </form>
    </Modal>
  );
}
