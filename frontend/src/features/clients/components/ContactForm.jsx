import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "../../../components/ui/Button";
import { Checkbox } from "../../../components/ui/Checkbox";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { applyServerErrors, EMAIL_PATTERN, PHONE_PATTERN } from "../../../lib/forms";
import { useContactMutations } from "../hooks/useContactMutations";

const FIELD_NAMES = ["name", "email", "phone", "position", "is_primary"];

function toFormValues(contact) {
  return {
    name: contact?.name ?? "",
    email: contact?.email ?? "",
    phone: contact?.phone ?? "",
    position: contact?.position ?? "",
    is_primary: contact?.is_primary ?? false,
  };
}

// Add/edit a person at the client (design doc §7.4 Contacts tab).
// `contact` null → create under clientId, object → edit via the flat route.
export function ContactForm({ isOpen, onClose, clientId, contact = null }) {
  const isEdit = contact != null;
  const { create, update } = useContactMutations(clientId);
  const mutation = isEdit ? update : create;

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm({
    defaultValues: toFormValues(contact),
    // Same instant-check behavior as ClientForm: validate on first blur,
    // then on every keystroke.
    mode: "onTouched",
  });

  useEffect(() => {
    if (isOpen) reset(toFormValues(contact));
  }, [isOpen, contact, reset]);

  function onSubmit(values) {
    mutation.mutate(isEdit ? { id: contact.id, ...values } : values, {
      onSuccess: () => onClose(),
      onError: (error) => applyServerErrors(error, setError, FIELD_NAMES),
    });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `Edit ${contact.name}` : "Add contact"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="contact-form" isLoading={mutation.isPending}>
            {isEdit ? "Save changes" : "Add contact"}
          </Button>
        </>
      }
    >
      <form id="contact-form" onSubmit={handleSubmit(onSubmit)} noValidate>
        {errors.root && (
          <p role="alert" className="mb-4 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {errors.root.message}
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input
            label="Name *"
            error={errors.name?.message}
            {...register("name", { required: "Name is required." })}
          />
          <Input
            label="Position"
            hint='e.g. "CTO", "Accounts"'
            error={errors.position?.message}
            {...register("position")}
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
          <Input
            label="Phone"
            hint="e.g. +91 98765 43210"
            error={errors.phone?.message}
            {...register("phone", {
              validate: (v) =>
                v.trim() === "" ||
                PHONE_PATTERN.test(v.trim()) ||
                "Enter a valid phone number, e.g. +91 98765 43210.",
            })}
          />
          <Checkbox
            label="Primary contact"
            hint="The main person we reach out to — checking this replaces the current primary."
            className="sm:col-span-2"
            {...register("is_primary")}
          />
        </div>
      </form>
    </Modal>
  );
}
