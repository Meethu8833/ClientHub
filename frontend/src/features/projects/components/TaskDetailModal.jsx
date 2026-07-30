import { useForm } from "react-hook-form";

import { Avatar } from "../../../components/ui/Avatar";
import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { Input } from "../../../components/ui/Input";
import { Modal } from "../../../components/ui/Modal";
import { Spinner } from "../../../components/ui/Spinner";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { PRIORITY, TASK_STATUS } from "../../../lib/constants";
import { applyServerErrors } from "../../../lib/forms";
import { formatDate } from "../../../lib/formatters";
import { useTask } from "../hooks/useTask";
import { useTaskMutations } from "../hooks/useTaskMutations";
import { useTaskTimeEntries } from "../hooks/useTimeEntries";

// Today in the browser's own timezone, as the ISO string <input type="date">
// wants. toISOString() would be wrong here: it converts to UTC first, so
// anyone east of Greenwich gets yesterday for most of their evening.
function todayISO() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function Field({ label, children }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500 dark:text-gray-400">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-900 dark:text-gray-100">{children || "—"}</dd>
    </div>
  );
}

// Logging time is open to every role that can see the task — the row is always
// yours, so there is no assignee picker and no permission check to mirror.
function LogTimeForm({ taskId }) {
  const { log } = useTaskMutations();
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm({
    defaultValues: { hours: "", worked_on: todayISO(), description: "" },
    mode: "onTouched",
  });

  function onSubmit(values) {
    log.mutate(
      { taskId, ...values },
      {
        onSuccess: () => reset({ hours: "", worked_on: todayISO(), description: "" }),
        onError: (error) =>
          applyServerErrors(error, setError, ["hours", "worked_on", "description"]),
      }
    );
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="mt-3 flex flex-wrap items-end gap-2"
    >
      {errors.root && (
        <p role="alert" className="w-full text-xs text-red-600 dark:text-red-400">
          {errors.root.message}
        </p>
      )}
      <Input
        label="Hours"
        type="number"
        step="0.25"
        min="0.01"
        max="24"
        className="w-24"
        error={errors.hours?.message}
        {...register("hours", {
          required: "Required.",
          validate: (v) => (Number(v) > 0 && Number(v) <= 24) || "Between 0.01 and 24 hours.",
        })}
      />
      <Input
        label="Date"
        type="date"
        max={todayISO()} // the API refuses future time
        className="w-44"
        error={errors.worked_on?.message}
        {...register("worked_on", { required: "Required." })}
      />
      <Input
        label="What did you do?"
        className="min-w-40 flex-1"
        error={errors.description?.message}
        {...register("description")}
      />
      <Button type="submit" isLoading={log.isPending}>
        Log
      </Button>
    </form>
  );
}

// Read-only task detail (design doc §7.4 in modal form). Editing happens in
// TaskForm — this pane is for reading the record, its dependency graph and
// its logged hours, plus the one write anyone may do: logging time.
export function TaskDetailModal({ taskId, isOpen, onClose, onEdit, canWrite }) {
  const { data: task, isPending, isError } = useTask(taskId, { enabled: isOpen });
  const { data: timePage } = useTaskTimeEntries(taskId, { enabled: isOpen });

  const entries = timePage?.results ?? [];

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={task?.title ?? "Task"}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          {canWrite && task && <Button onClick={() => onEdit(task)}>Edit task</Button>}
        </>
      }
    >
      {isPending && (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      )}

      {isError && (
        <p className="py-6 text-center text-sm text-gray-500 dark:text-gray-400">
          This task could not be loaded. It may have been deleted.
        </p>
      )}

      {task && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge map={TASK_STATUS} value={task.status} />
            <StatusBadge map={PRIORITY} value={task.priority} />
            {task.is_overdue && <Badge color="red">Overdue</Badge>}
            {task.sprint && <Badge color="indigo">{task.sprint.name}</Badge>}
          </div>

          {task.description && (
            <p className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300">
              {task.description}
            </p>
          )}

          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
            <Field label="Project">{task.project?.name}</Field>
            <Field label="Milestone">{task.milestone?.title}</Field>
            <Field label="Assignee">
              {task.assignee && (
                <span className="flex items-center gap-1.5">
                  <Avatar name={task.assignee.name} size="sm" />
                  {task.assignee.name}
                </span>
              )}
            </Field>
            <Field label="Due">{formatDate(task.due_date)}</Field>
            <Field label="Story points">{task.story_points}</Field>
            <Field label="Hours">
              {/* Estimate vs actual side by side — the number that matters is
                  the comparison, not either figure alone. */}
              {task.logged_hours} logged
              {task.estimated_hours ? ` / ${task.estimated_hours} estimated` : ""}
            </Field>
          </dl>

          {(task.blocked_by?.length > 0 || task.blocks?.length > 0) && (
            <div className="space-y-2 rounded-md bg-gray-50 p-3 dark:bg-gray-800/60">
              {task.blocked_by?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                    Blocked by — this task stays in To do until these are done
                  </p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {task.blocked_by.map((b) => (
                      <li key={b.id}>
                        <Badge color={b.status === "done" ? "green" : "red"}>
                          {b.title} ({TASK_STATUS[b.status]?.label ?? b.status})
                        </Badge>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {task.blocks?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                    Blocks — these are waiting on this task
                  </p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {task.blocks.map((b) => (
                      <li key={b.id}>
                        <Badge>{b.title}</Badge>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          <div className="border-t border-gray-200 pt-4 dark:border-gray-800">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              Time log
              {/* Staff see only their own rows — the server filters, so this
                  count is "yours", not "everyone's", for them. */}
              {entries.length > 0 && (
                <span className="ml-2 text-xs font-normal text-gray-500 dark:text-gray-400">
                  {entries.length} {entries.length === 1 ? "entry" : "entries"}
                </span>
              )}
            </h3>

            {entries.length > 0 ? (
              <ul className="mt-2 divide-y divide-gray-100 dark:divide-gray-800">
                {entries.map((entry) => (
                  <li key={entry.id} className="flex items-baseline justify-between gap-3 py-1.5">
                    <span className="text-sm text-gray-900 dark:text-gray-100">
                      <span className="font-medium tabular-nums">{entry.hours} h</span>
                      {entry.description && (
                        <span className="ml-2 text-gray-600 dark:text-gray-400">
                          {entry.description}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 text-xs text-gray-500 dark:text-gray-400">
                      {entry.user.name} · {formatDate(entry.worked_on)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">No time logged yet.</p>
            )}

            <LogTimeForm taskId={task.id} />
          </div>
        </div>
      )}
    </Modal>
  );
}
