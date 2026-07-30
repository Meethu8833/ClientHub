import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";

import { Button } from "../../../components/ui/Button";
import { Checkbox } from "../../../components/ui/Checkbox";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Select } from "../../../components/ui/Select";
import { PRIORITY_OPTIONS, PROJECT_STATUS_OPTIONS } from "../../../lib/constants";
import { applyServerErrors, toIdArray } from "../../../lib/forms";
import { useClientOptions } from "../hooks/useClientOptions";
import { useProjectMutations } from "../hooks/useProjectMutations";
import { useTechnologies } from "../hooks/useTechnologies";

// Everything ProjectWriteSerializer accepts that this form renders. Server
// 400s for these land on the matching field; anything else becomes the root
// banner.
const FIELD_NAMES = [
  "name",
  "client_id",
  "description",
  "status",
  "priority",
  "start_date",
  "end_date",
  "budget",
  "technology_ids",
];

function toFormValues(project) {
  return {
    name: project?.name ?? "",
    // Reads embed the client as an object; the write field wants a plain id.
    client_id: project?.client?.id ?? "",
    description: project?.description ?? "",
    status: project?.status ?? "planned",
    priority: project?.priority ?? "medium",
    // <input type="date"> speaks ISO — which is exactly what DRF sends back.
    start_date: project?.start_date ?? "",
    end_date: project?.end_date ?? "",
    // budget is absent from the payload for STAFF; they never reach this form
    // (the API refuses their writes), but default defensively anyway.
    budget: project?.budget ?? "",
    // Checkbox group → react-hook-form collects the checked values as an
    // array of strings; onSubmit casts them back to numbers.
    technology_ids: project?.technologies?.map((t) => String(t.id)) ?? [],
  };
}

// Create + edit in one component (archetype D): `project` null → create,
// object → edit. Mutations, cache invalidation and toasts live in
// useProjectMutations — this form only renders, validates and maps.
// `defaultClient` ({id, name}) pre-points a create form at one client — used
// by the client detail page's Projects tab. It is the whole object, not just
// an id, so the option can be guaranteed present even when the client sits
// outside the first page the picker loaded.
export function ProjectForm({ isOpen, onClose, project = null, defaultClient = null }) {
  const isEdit = project != null;
  const { create, update } = useProjectMutations();
  const mutation = isEdit ? update : create;

  const { data: clientData } = useClientOptions({ enabled: isOpen && !isEdit });
  const { data: technologies } = useTechnologies({ enabled: isOpen });

  const {
    register,
    handleSubmit,
    reset,
    setError,
    watch,
    formState: { errors },
  } = useForm({
    defaultValues: toFormValues(project),
    // Each field validates on its first blur, then on every keystroke.
    mode: "onTouched",
  });

  // Re-arm the form each time the modal opens: a fresh create form (optionally
  // pre-pointed at a client, e.g. from a client's Projects tab), or the
  // current record's values on edit.
  useEffect(() => {
    if (!isOpen) return;
    const values = toFormValues(project);
    if (!isEdit && defaultClient) values.client_id = String(defaultClient.id);
    reset(values);
  }, [isOpen, project, isEdit, defaultClient, reset]);

  const clientOptions = useMemo(() => {
    const options = clientData?.clients?.map((c) => ({ value: c.id, label: c.name })) ?? [];
    // The picker holds one page; a pre-selected client from outside it would
    // otherwise render as the empty placeholder and look unset.
    if (defaultClient && !options.some((o) => String(o.value) === String(defaultClient.id))) {
      return [{ value: defaultClient.id, label: defaultClient.name }, ...options];
    }
    return options;
  }, [clientData, defaultClient]);

  // The picker holds at most one page (the API caps page_size at 100). Say so
  // rather than letting a missing client look like a deleted one.
  const truncated = clientData && clientData.total > clientData.clients.length;

  // End date can't precede start date — the same rule the serializer enforces,
  // checked here so the user hears about it before a round-trip.
  const startDate = watch("start_date");

  function onSubmit(values) {
    const payload = {
      name: values.name.trim(),
      description: values.description.trim(),
      status: values.status,
      priority: values.priority,
      // "" is the empty <input type="date"> / <Select>; the API wants null.
      start_date: values.start_date || null,
      end_date: values.end_date || null,
      budget: values.budget === "" ? null : values.budget,
      technology_ids: toIdArray(values.technology_ids),
    };
    // A project never moves to another client — the serializer rejects the
    // field on update, so it is only sent at create time.
    if (!isEdit) payload.client_id = Number(values.client_id);

    mutation.mutate(isEdit ? { id: project.id, ...payload } : payload, {
      onSuccess: () => onClose(),
      onError: (error) => applyServerErrors(error, setError, FIELD_NAMES),
    });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? `Edit ${project.name}` : "New project"}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="project-form" isLoading={mutation.isPending}>
            {isEdit ? "Save changes" : "Create project"}
          </Button>
        </>
      }
    >
      {/* id + the footer button's form="" attribute connect them across the
          modal layout — the submit button lives outside the <form> element. */}
      <form id="project-form" onSubmit={handleSubmit(onSubmit)} noValidate>
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
          <Input
            label="Project name *"
            className="sm:col-span-2"
            error={errors.name?.message}
            {...register("name", { required: "Project name is required." })}
          />

          {isEdit ? (
            // Immutable after creation (the serializer refuses a change), so
            // show it as a fact rather than a disabled control that invites
            // clicking.
            <div className="sm:col-span-2">
              <span className="block text-sm font-medium text-gray-700 dark:text-gray-200">
                Client
              </span>
              <p className="mt-1 text-sm text-gray-900 dark:text-gray-100">
                {project.client?.name ?? "—"}
                <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                  (a project cannot be moved to another client)
                </span>
              </p>
            </div>
          ) : (
            <Select
              label="Client *"
              placeholder="— Select a client —"
              options={clientOptions}
              className="sm:col-span-2"
              hint={truncated ? "Showing the first 100 clients by name." : undefined}
              error={errors.client_id?.message}
              {...register("client_id", { required: "Pick the client this project is for." })}
            />
          )}

          <Select
            label="Status"
            options={PROJECT_STATUS_OPTIONS}
            error={errors.status?.message}
            {...register("status")}
          />
          <Select
            label="Priority"
            options={PRIORITY_OPTIONS}
            error={errors.priority?.message}
            {...register("priority")}
          />

          <Input
            label="Start date"
            type="date"
            error={errors.start_date?.message}
            {...register("start_date")}
          />
          <Input
            label="End date"
            type="date"
            error={errors.end_date?.message}
            {...register("end_date", {
              validate: (v) =>
                !v || !startDate || v >= startDate || "End date cannot be before the start date.",
            })}
          />

          <Input
            label="Budget"
            type="number"
            step="0.01"
            min="0"
            hint="Visible to managers and admins only."
            className="sm:col-span-2"
            error={errors.budget?.message}
            {...register("budget", {
              validate: (v) => v === "" || Number(v) >= 0 || "Budget cannot be negative.",
            })}
          />

          <div className="sm:col-span-2">
            <label
              htmlFor="project-description"
              className="block text-sm font-medium text-gray-700 dark:text-gray-200"
            >
              Description
            </label>
            <textarea
              id="project-description"
              rows={3}
              className="mt-1 block w-full rounded-md border-0 px-3 py-2 text-gray-900 shadow-sm
                ring-1 ring-inset ring-gray-300 placeholder:text-gray-400 focus:ring-2
                focus:ring-inset focus:ring-indigo-600 sm:text-sm dark:bg-gray-800
                dark:text-gray-100 dark:ring-gray-600 dark:focus:ring-indigo-400"
              {...register("description")}
            />
          </div>

          {/* Checkbox group rather than a <select multiple>: multi-selects are
              notoriously hard to operate (ctrl-click to deselect) and hide
              their options. Same name on every box → RHF gives back an array. */}
          <fieldset className="sm:col-span-2">
            <legend className="text-sm font-medium text-gray-700 dark:text-gray-200">
              Tech stack
            </legend>
            {technologies?.length ? (
              <div
                className="mt-2 grid max-h-40 grid-cols-2 gap-2 overflow-y-auto rounded-md
                  p-2 ring-1 ring-gray-200 sm:grid-cols-3 dark:ring-gray-700"
              >
                {technologies.map((tech) => (
                  <Checkbox
                    key={tech.id}
                    label={tech.name}
                    value={String(tech.id)}
                    {...register("technology_ids")}
                  />
                ))}
              </div>
            ) : (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                No technologies defined yet.
              </p>
            )}
          </fieldset>
        </div>
      </form>
    </Modal>
  );
}
