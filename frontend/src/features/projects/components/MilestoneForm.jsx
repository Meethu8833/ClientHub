import { useEffect } from "react";
import { useForm } from "react-hook-form";

import { Button } from "../../../components/ui/Button";
import { Checkbox } from "../../../components/ui/Checkbox";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { applyServerErrors } from "../../../lib/forms";
import { useMilestoneMutations } from "../hooks/useMilestoneMutations";

const FIELD_NAMES = ["title", "description", "due_date", "is_completed"];

function toFormValues(milestone) {
  return {
    title: milestone?.title ?? "",
    description: milestone?.description ?? "",
    due_date: milestone?.due_date ?? "",
    is_completed: milestone?.is_completed ?? false,
  };
}

// Create + edit for milestones. `completed_at` is service-managed on the
// backend — the form only ever sends the boolean, never a timestamp.
export function MilestoneForm({ isOpen, onClose, projectId, milestone = null }) {
  const isEdit = milestone != null;
  const { create, update } = useMilestoneMutations(projectId);
  const mutation = isEdit ? update : create;

  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm({ defaultValues: toFormValues(milestone), mode: "onTouched" });

  useEffect(() => {
    if (isOpen) reset(toFormValues(milestone));
  }, [isOpen, milestone, reset]);

  function onSubmit(values) {
    const payload = {
      title: values.title.trim(),
      description: values.description.trim(),
      due_date: values.due_date,
      is_completed: values.is_completed,
    };
    mutation.mutate(isEdit ? { id: milestone.id, ...payload } : payload, {
      onSuccess: () => onClose(),
      onError: (error) => applyServerErrors(error, setError, FIELD_NAMES),
    });
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? "Edit milestone" : "New milestone"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button type="submit" form="milestone-form" isLoading={mutation.isPending}>
            {isEdit ? "Save changes" : "Add milestone"}
          </Button>
        </>
      }
    >
      <form id="milestone-form" onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        {errors.root && (
          <p
            role="alert"
            className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700
              dark:bg-red-500/10 dark:text-red-300"
          >
            {errors.root.message}
          </p>
        )}

        <Input
          label="Title *"
          error={errors.title?.message}
          {...register("title", { required: "A milestone needs a title." })}
        />
        <Input
          label="Due date *"
          type="date"
          error={errors.due_date?.message}
          {...register("due_date", { required: "A milestone needs a due date." })}
        />
        <div>
          <label
            htmlFor="milestone-description"
            className="block text-sm font-medium text-gray-700 dark:text-gray-200"
          >
            Description
          </label>
          <textarea
            id="milestone-description"
            rows={3}
            className="mt-1 block w-full rounded-md border-0 px-3 py-2 text-gray-900 shadow-sm
              ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-indigo-600
              sm:text-sm dark:bg-gray-800 dark:text-gray-100 dark:ring-gray-600
              dark:focus:ring-indigo-400"
            {...register("description")}
          />
        </div>
        <Checkbox
          label="Completed"
          hint="Ticking this stamps the completion time server-side."
          {...register("is_completed")}
        />
      </form>
    </Modal>
  );
}
