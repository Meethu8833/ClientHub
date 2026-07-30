import { useState } from "react";

import { Button } from "../../../components/ui/Button";
import { Spinner } from "../../../components/ui/Spinner";
import { ROLES, TASK_STATUS, TASK_STATUS_ORDER } from "../../../lib/constants";
import { useAuth } from "../../auth/useAuth";
import { useTasks } from "../hooks/useTasks";
import { TaskCard } from "./TaskCard";

// The board loads one query PER COLUMN rather than one big list split in JS.
// That way a card landing in "Review" refetches only that column and the one
// it left, the columns page independently, and each column's count is the
// server's count — not "how many of the first 100 rows happened to be here".
const COLUMN_PAGE_SIZE = 100;

function Column({ status, projectId, extraParams, onDropTask, canMove, children, cardProps }) {
  const [isOver, setIsOver] = useState(false);
  const { data, isPending } = useTasks({
    project: projectId,
    status,
    page_size: COLUMN_PAGE_SIZE,
    ...extraParams,
  });

  const meta = TASK_STATUS[status];
  const tasks = data?.results ?? [];
  // The column holds one page; past that the count is still truthful, so say
  // how many are hidden instead of pretending the column ends here.
  const hidden = data ? data.count - tasks.length : 0;

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault(); // without this the drop event never fires
        e.dataTransfer.dropEffect = "move";
        setIsOver(true);
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsOver(false);
        try {
          const { id, from } = JSON.parse(e.dataTransfer.getData("text/plain"));
          if (from !== status) onDropTask(id, status);
        } catch {
          // A drag from outside the board (a file, selected text) — ignore it.
        }
      }}
      className={`flex min-w-64 flex-1 flex-col rounded-lg bg-gray-50 p-3 ring-1 transition-colors
        dark:bg-gray-950/40 ${
          isOver
            ? "ring-2 ring-indigo-500 dark:ring-indigo-400"
            : "ring-gray-200 dark:ring-gray-800"
        }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {meta.label}
          <span className="ml-2 rounded-full bg-gray-200 px-2 py-0.5 text-xs font-normal text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            {data?.count ?? "—"}
          </span>
        </h3>
      </div>

      {isPending ? (
        <div className="flex justify-center py-8">
          <Spinner size="sm" />
        </div>
      ) : (
        <ul className="flex flex-1 flex-col gap-2">
          {tasks.map((task) => (
            <TaskCard key={task.id} task={task} canMove={canMove(task)} {...cardProps} />
          ))}
          {tasks.length === 0 && (
            <li className="rounded-md border border-dashed border-gray-300 px-3 py-6 text-center text-xs text-gray-400 dark:border-gray-700 dark:text-gray-500">
              {/* The dashed box doubles as the drop target's "here" cue. */}
              Nothing here
            </li>
          )}
          {hidden > 0 && (
            <li className="px-1 pt-1 text-xs text-gray-500 dark:text-gray-400">
              +{hidden} more — narrow the filters to see them
            </li>
          )}
        </ul>
      )}

      {children}
    </div>
  );
}

// Kanban board for one project (design doc §7.5). Columns come from
// TASK_STATUS_ORDER, so the board and the badge map can never disagree.
export function TaskBoard({
  projectId,
  filters = {},
  onOpenTask,
  onEditTask,
  onDeleteTask,
  onMoveTask,
  onCreateTask,
  canWrite,
}) {
  const { user } = useAuth();

  // Who may move which card, mirroring the API so the UI never offers an
  // action that will 403: managers/admins move anything on the project;
  // STAFF may change the status of tasks assigned to them, and nothing else.
  function canMove(task) {
    if (user?.role !== ROLES.STAFF) return true;
    return task.assignee?.id === user.id;
  }

  const cardProps = {
    onOpen: onOpenTask,
    onEdit: onEditTask,
    onDelete: onDeleteTask,
    onMove: (task, status) => onMoveTask(task.id, status),
    canWrite,
  };

  return (
    <div className="flex gap-4 overflow-x-auto pb-2">
      {TASK_STATUS_ORDER.map((status) => (
        <Column
          key={status}
          status={status}
          projectId={projectId}
          extraParams={filters}
          onDropTask={onMoveTask}
          canMove={canMove}
          cardProps={cardProps}
        >
          {/* New tasks always start in To do (the dependency gate would refuse
              anything else), so only that column offers the shortcut. */}
          {canWrite && status === "todo" && (
            <Button variant="ghost" className="mt-2 w-full" onClick={onCreateTask}>
              + Add task
            </Button>
          )}
        </Column>
      ))}
    </div>
  );
}
