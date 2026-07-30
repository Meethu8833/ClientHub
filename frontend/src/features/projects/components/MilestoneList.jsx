import { useState } from "react";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { EmptyState } from "../../../components/ui/EmptyState";
import { formatDate } from "../../../lib/formatters";
import { useMilestoneMutations } from "../hooks/useMilestoneMutations";
import { MilestoneForm } from "./MilestoneForm";

// Milestones tab. The project's `progress` percentage is computed from these
// rows server-side, so ticking one here is what moves the bar on the list page.
export function MilestoneList({ project, canWrite }) {
  const { toggle, remove } = useMilestoneMutations(project.id);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const milestones = project.milestones ?? [];

  function openCreate() {
    setEditing(null);
    setIsFormOpen(true);
  }

  return (
    <div>
      {canWrite && (
        <div className="mb-4 flex justify-end">
          <Button variant="secondary" onClick={openCreate}>
            + Add milestone
          </Button>
        </div>
      )}

      {milestones.length === 0 ? (
        <EmptyState
          icon="🎯"
          title="No milestones yet"
          message="Milestones are how this project reports progress — without them the
            progress bar stays blank."
          action={canWrite && <Button onClick={openCreate}>+ Add milestone</Button>}
        />
      ) : (
        <ul className="space-y-2">
          {milestones.map((milestone) => (
            <li
              key={milestone.id}
              className="flex items-start justify-between gap-3 rounded-lg bg-white p-4
                shadow-sm ring-1 ring-gray-200 dark:bg-gray-900 dark:ring-gray-800"
            >
              <div className="flex items-start gap-3">
                {/* A bare checkbox with no <label> would be unreachable by name,
                    so the accessible name is spelled out here. */}
                <input
                  type="checkbox"
                  checked={milestone.is_completed}
                  disabled={!canWrite || toggle.isPending}
                  aria-label={`Mark "${milestone.title}" complete`}
                  onChange={(e) =>
                    toggle.mutate({ id: milestone.id, is_completed: e.target.checked })
                  }
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600
                    focus:ring-indigo-600 disabled:opacity-50 dark:border-gray-600
                    dark:bg-gray-800"
                />
                <div>
                  <p
                    className={`flex flex-wrap items-center gap-2 text-sm font-medium ${
                      milestone.is_completed
                        ? "text-gray-400 line-through dark:text-gray-500"
                        : "text-gray-900 dark:text-gray-50"
                    }`}
                  >
                    {milestone.title}
                    {milestone.is_overdue && <Badge color="red">Overdue</Badge>}
                    {milestone.is_completed && <Badge color="green">Done</Badge>}
                  </p>
                  {milestone.description && (
                    <p className="mt-0.5 text-sm text-gray-600 dark:text-gray-400">
                      {milestone.description}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    Due {formatDate(milestone.due_date)}
                    {milestone.completed_at && ` · completed ${formatDate(milestone.completed_at)}`}
                  </p>
                </div>
              </div>

              {canWrite && (
                <DropdownMenu
                  label={`Actions for ${milestone.title}`}
                  items={[
                    {
                      label: "Edit",
                      onClick: () => {
                        setEditing(milestone);
                        setIsFormOpen(true);
                      },
                    },
                    {
                      label: "Delete",
                      tone: "danger",
                      onClick: () => setDeleteTarget(milestone),
                    },
                  ]}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <MilestoneForm
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        projectId={project.id}
        milestone={editing}
      />

      <ConfirmDialog
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => remove.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })}
        isPending={remove.isPending}
        title={`Delete "${deleteTarget?.title}"?`}
        message="Tasks pointing at this milestone keep existing — they just stop
          being grouped under it."
      />
    </div>
  );
}
