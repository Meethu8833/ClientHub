import { Link } from "react-router-dom";

import { Avatar } from "../../../components/ui/Avatar";
import { Badge } from "../../../components/ui/Badge";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { Table } from "../../../components/ui/Table";
import { PRIORITY, TASK_STATUS, TASK_STATUS_ORDER } from "../../../lib/constants";
import { formatDate } from "../../../lib/formatters";

// The cross-project task table. The board is the per-project view; this one
// answers "what is on my plate" and "what is overdue everywhere".
export function TaskTable({
  rows,
  isLoading,
  sort,
  onSortChange,
  onOpen,
  onEdit,
  onDelete,
  onMove,
  canWrite,
  canMove,
  emptyState,
}) {
  const columns = [
    {
      key: "title",
      header: "Task",
      sortable: true,
      render: (t) => (
        <span className="flex items-center gap-2">
          <span className="font-medium">{t.title}</span>
          {t.open_blockers > 0 && <Badge color="red">⛔ {t.open_blockers}</Badge>}
        </span>
      ),
    },
    {
      key: "project",
      header: "Project",
      render: (t) =>
        t.project ? (
          // stopPropagation: the row itself opens the task modal, and a link
          // inside a clickable row must win rather than do both.
          <Link
            to={`/projects/${t.project.id}`}
            onClick={(e) => e.stopPropagation()}
            className="text-indigo-600 hover:underline dark:text-indigo-400"
          >
            {t.project.name}
          </Link>
        ) : (
          "—"
        ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (t) => <StatusBadge map={TASK_STATUS} value={t.status} />,
    },
    {
      key: "priority",
      header: "Priority",
      sortable: true,
      render: (t) => <StatusBadge map={PRIORITY} value={t.priority} />,
    },
    {
      key: "assignee",
      header: "Assignee",
      render: (t) =>
        t.assignee ? (
          <span className="flex items-center gap-2">
            <Avatar name={t.assignee.name} size="sm" />
            <span className="text-gray-600 dark:text-gray-300">{t.assignee.name}</span>
          </span>
        ) : (
          <span className="text-gray-400 dark:text-gray-500">Unassigned</span>
        ),
    },
    {
      key: "due_date",
      header: "Due",
      sortable: true,
      render: (t) => (
        <span
          className={
            t.is_overdue
              ? "font-medium text-red-600 dark:text-red-400"
              : "text-gray-600 dark:text-gray-300"
          }
        >
          {t.is_overdue && <span className="sr-only">Overdue: </span>}
          {formatDate(t.due_date)}
        </span>
      ),
    },
    {
      key: "logged_hours",
      header: "Hours",
      render: (t) => (
        <span className="tabular-nums text-gray-600 dark:text-gray-300">
          {t.logged_hours}
          {t.estimated_hours ? ` / ${t.estimated_hours}` : ""}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      className: "w-12 text-right",
      render: (t) => {
        const items = [
          { label: "Open", onClick: () => onOpen(t) },
          ...(canMove(t)
            ? TASK_STATUS_ORDER.filter((s) => s !== t.status).map((s) => ({
                label: `Move to ${TASK_STATUS[s].label}`,
                onClick: () => onMove(t, s),
              }))
            : []),
          ...(canWrite
            ? [
                { label: "Edit", onClick: () => onEdit(t) },
                { label: "Delete", tone: "danger", onClick: () => onDelete(t) },
              ]
            : []),
        ];
        return <DropdownMenu label={`Actions for ${t.title}`} items={items} />;
      },
    },
  ];

  return (
    <Table
      columns={columns}
      rows={rows}
      isLoading={isLoading}
      sort={sort}
      onSortChange={onSortChange}
      onRowClick={onOpen}
      emptyState={emptyState}
    />
  );
}
