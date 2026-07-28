import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "../../../components/ui/Button";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import { applyServerErrors } from "../../../lib/forms";
import { CLIENT_STATUS_OPTIONS } from "../../../lib/constants";
import { useAssignableUsers } from "../hooks/useAssignableUsers";
import { useClientMutations } from "../hooks/useClientMutations";

// Matches the model's GSTIN RegexValidator — same rule client-side so the
// user hears about a typo before a round-trip. The server stays the real
// validator (client checks are UX, never security).
const GSTIN_PATTERN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

// Everything ClientWriteSerializer accepts that this form renders. Server
// 400s for these land on the matching field; anything else becomes the
// root banner.
const FIELD_NAMES = [
  "name",
  "industry",
  "website",
  "email",
  "phone",
  "gst_number",
  "city",
  "status",
  "account_manager_id",
];

function toFormValues(client) {
  return {
    name: client?.name ?? "",
    industry: client?.industry ?? "",
    website: client?.website ?? "",
    email: client?.email ?? "",
    phone: client?.phone ?? "",
    gst_number: client?.gst_number ?? "",
    city: client?.city ?? "",
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
    formState: { errors },
  } = useForm({ defaultValues: toFormValues(client) });

  // Re-arm the form each time the modal opens: a fresh create form, or the
  // current record's values on edit (stale defaults from a previous open
  // would otherwise leak through).
  useEffect(() => {
    if (isOpen) reset(toFormValues(client));
  }, [isOpen, client, reset]);

  function onSubmit(values) {
    const payload = {
      ...values,
      // "" is <Select>'s "nobody chosen"; the API wants an explicit null.
      account_manager_id:
        values.account_manager_id === "" ? null : Number(values.account_manager_id),
      gst_number: values.gst_number.trim().toUpperCase(),
    };
    mutation.mutate(isEdit ? { id: client.id, ...payload } : payload, {
      onSuccess: () => onClose(),
      onError: (error) => applyServerErrors(error, setError, FIELD_NAMES),
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
            {...register("name", { required: "Company name is required." })}
          />
          <Input label="Industry" error={errors.industry?.message} {...register("industry")} />
          <Input
            label="Website"
            type="url"
            hint="Include the scheme, e.g. https://acme.com"
            error={errors.website?.message}
            {...register("website")}
          />
          <Input label="Email" type="email" error={errors.email?.message} {...register("email")} />
          <Input label="Phone" error={errors.phone?.message} {...register("phone")} />
          <Input
            label="GSTIN"
            hint="15 characters, e.g. 29ABCDE1234F1Z5 — leave blank if unregistered"
            error={errors.gst_number?.message}
            {...register("gst_number", {
              validate: (v) =>
                v.trim() === "" ||
                GSTIN_PATTERN.test(v.trim().toUpperCase()) ||
                "Enter a valid 15-character GSTIN, e.g. 29ABCDE1234F1Z5.",
            })}
          />
          <Input label="City" error={errors.city?.message} {...register("city")} />
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
