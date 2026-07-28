import { Avatar } from "../../../components/ui/Avatar";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { Table } from "../../../components/ui/Table";
import { CLIENT_STATUS } from "../../../lib/constants";
import { formatDate } from "../../../lib/formatters";

// The clients table (design doc §7.3). Pure presentation: which rows, which
// sort, what happens on click/edit/delete all come from the page — so the
// same table could later render e.g. "clients of this account manager".
export function ClientTable({
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
      header: "Name",
      sortable: true,
      render: (c) => <span className="font-medium">{c.name}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (c) => <StatusBadge map={CLIENT_STATUS} value={c.status} />,
    },
    { key: "industry", header: "Industry", render: (c) => c.industry || "—" },
    {
      key: "account_manager",
      header: "Acct manager",
      render: (c) =>
        c.account_manager ? (
          <span className="flex items-center gap-2">
            <Avatar name={c.account_manager.name} size="sm" />
            <span className="text-gray-600">{c.account_manager.name}</span>
          </span>
        ) : (
          <span className="text-gray-400">Unassigned</span>
        ),
    },
    {
      key: "contact_count",
      header: "Contacts",
      render: (c) => <span className="text-gray-600">{c.contact_count}</span>,
    },
    {
      key: "created_at",
      header: "Created",
      sortable: true,
      render: (c) => <span className="text-gray-600">{formatDate(c.created_at)}</span>,
    },
    // The actions column only exists for roles that can act — STAFF sees a
    // clean table, not a row of disabled buttons (matrix §8: read-only).
    ...(canWrite
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            className: "w-12 text-right",
            render: (c) => (
              <DropdownMenu
                label={`Actions for ${c.name}`}
                items={[
                  { label: "Edit", onClick: () => onEdit(c) },
                  { label: "Delete", tone: "danger", onClick: () => onDelete(c) },
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
