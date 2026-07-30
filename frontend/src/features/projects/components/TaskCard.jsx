import { Avatar } from "../../../components/ui/Avatar";
import { Badge } from "../../../components/ui/Badge";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { PRIORITY, TASK_STATUS, TASK_STATUS_ORDER } from "../../../lib/constants";
import { formatDate } from "../../../lib/formatters";

// One kanban card.
//
// Dragging is a mouse affordance; the ⋯ menu carries the same "Move to …"
// actions so the board is fully operable from the keyboard (a11y floor §3.3).
// Never make drag the only way to move a card.
export function TaskCard({ task, onOpen, onEdit, onDelete, onMove, canWrite, canMove }) {
  const menuItems = [
    { label: "Open", onClick: () => onOpen(task) },
    ...(canMove
      ? TASK_STATUS_ORDER.filter((s) => s !== task.status).map((s) => ({
          label: `Move to ${TASK_STATUS[s].label}`,
          onClick: () => onMove(task, s),
        }))
      : []),
    ...(canWrite
      ? [
          { label: "Edit", onClick: () => onEdit(task) },
          { label: "Delete", tone: "danger", onClick: () => onDelete(task) },
        ]
      : []),
  ];

  return (
    <li
      // draggable only when the user may actually move this card — otherwise
      // the drag would always end in a 403 toast.
      draggable={canMove}
      onDragStart={(e) => {
        // text/plain is the one format every browser reliably round-trips.
        // The payload carries the source status too, so the drop target can
        // ignore a card dropped back on its own column without a round-trip.
        e.dataTransfer.setData("text/plain", JSON.stringify({ id: task.id, from: task.status }));
        e.dataTransfer.effectAllowed = "move";
      }}
      className={`rounded-lg bg-white p-3 shadow-sm ring-1 ring-gray-200
        dark:bg-gray-900 dark:ring-gray-800 ${canMove ? "cursor-grab active:cursor-grabbing" : ""}`}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => onOpen(task)}
          className="text-left text-sm font-medium text-gray-900 hover:text-indigo-600
            focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600
            dark:text-gray-100 dark:hover:text-indigo-400"
        >
          {task.title}
        </button>
        <DropdownMenu label={`Actions for ${task.title}`} items={menuItems} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <StatusBadge map={PRIORITY} value={task.priority} />
        {task.story_points != null && <Badge>{task.story_points} pts</Badge>}
        {/* A blocked card explains itself on the card — otherwise a refused
            move is the first the user hears of the dependency. */}
        {task.open_blockers > 0 && (
          <Badge color="red">
            ⛔ {task.open_blockers} blocker{task.open_blockers === 1 ? "" : "s"}
          </Badge>
        )}
        {task.sprint && <Badge color="indigo">{task.sprint.name}</Badge>}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs">
          {task.assignee ? (
            <>
              <Avatar name={task.assignee.name} size="sm" />
              <span className="text-gray-600 dark:text-gray-300">{task.assignee.name}</span>
            </>
          ) : (
            <span className="text-gray-400 dark:text-gray-500">Unassigned</span>
          )}
        </span>
        {task.due_date && (
          <span
            className={`text-xs ${
              task.is_overdue
                ? "font-medium text-red-600 dark:text-red-400"
                : "text-gray-500 dark:text-gray-400"
            }`}
          >
            {task.is_overdue && <span className="sr-only">Overdue: </span>}
            {formatDate(task.due_date)}
          </span>
        )}
      </div>
    </li>
  );
}
