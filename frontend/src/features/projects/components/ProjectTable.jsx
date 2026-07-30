import { Badge } from "../../../components/ui/Badge";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { Table } from "../../../components/ui/Table";
import { PRIORITY, PROJECT_STATUS } from "../../../lib/constants";
import { formatDate } from "../../../lib/formatters";

// Milestone completion as a bar. `progress` is null — not 0 — when a project
// has no milestones at all, and those are different facts: "nothing planned
// yet" must not render as "0% done, badly behind".
function ProgressBar({ value }) {
  if (value == null) {
    return <span className="text-xs text-gray-400 dark:text-gray-500">No milestones</span>;
  }
  return (
    <span className="flex items-center gap-2">
      <span
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Milestone progress"
        className="h-1.5 w-20 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
      >
        <span
          className="block h-full rounded-full bg-indigo-600 dark:bg-indigo-500"
          style={{ width: `${value}%` }}
        />
      </span>
      {/* The number repeats the bar in text — width alone is not a label. */}
      <span className="text-xs tabular-nums text-gray-600 dark:text-gray-300">{value}%</span>
    </span>
  );
}

// The projects table. Pure presentation, like ClientTable: rows, sort and
// every action come from the page.
export function ProjectTable({
  rows,
  isLoading,
  sort,
  onSortChange,
  onRowClick,
  onEdit,
  onDelete,
  canWrite,
  emptyState,
}) {
  const columns = [
    {
      key: "name",
      header: "Project",
      sortable: true,
      render: (p) => (
        <span className="block">
          <span className="font-medium">{p.name}</span>
          {/* The stack is context, not a column of its own — two tags keep the
              row scannable, the rest becomes "+3". */}
          {p.technologies?.length > 0 && (
            <span className="mt-0.5 flex flex-wrap gap-1">
              {p.technologies.slice(0, 2).map((tech) => (
                <Badge key={tech.id}>{tech.name}</Badge>
              ))}
              {p.technologies.length > 2 && <Badge>+{p.technologies.length - 2}</Badge>}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "client",
      header: "Client",
      render: (p) => (
        <span className="text-gray-600 dark:text-gray-300">{p.client?.name ?? "—"}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (p) => <StatusBadge map={PROJECT_STATUS} value={p.status} />,
    },
    {
      key: "priority",
      header: "Priority",
      sortable: true,
      render: (p) => <StatusBadge map={PRIORITY} value={p.priority} />,
    },
    { key: "progress", header: "Progress", render: (p) => <ProgressBar value={p.progress} /> },
    {
      key: "member_count",
      header: "Team",
      render: (p) => <span className="text-gray-600 dark:text-gray-300">{p.member_count}</span>,
    },
    {
      key: "end_date",
      header: "Due",
      sortable: true,
      render: (p) => (
        <span className="text-gray-600 dark:text-gray-300">{formatDate(p.end_date)}</span>
      ),
    },
    // Actions only exist for roles that can act — STAFF get a clean table
    // rather than a row of disabled buttons (matrix §8: read-only).
    ...(canWrite
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            className: "w-12 text-right",
            render: (p) => (
              <DropdownMenu
                label={`Actions for ${p.name}`}
                items={[
                  { label: "Edit", onClick: () => onEdit(p) },
                  { label: "Delete", tone: "danger", onClick: () => onDelete(p) },
                ]}
              />
            ),
          },
        ]
      : []),
  ];

  return (
    <Table
      columns={columns}
      rows={rows}
      isLoading={isLoading}
      sort={sort}
      onSortChange={onSortChange}
      onRowClick={onRowClick}
      emptyState={emptyState}
    />
  );
}
