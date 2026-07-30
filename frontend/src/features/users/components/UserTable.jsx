import { Avatar } from "../../../components/ui/Avatar";
import { DropdownMenu } from "../../../components/ui/DropdownMenu";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { Table } from "../../../components/ui/Table";
import { USER_ACTIVE_STATUS, USER_ROLE } from "../../../lib/constants";
import { formatDate } from "../../../lib/formatters";

// The users table (design doc §7.10). Pure presentation — the page owns the
// data, the sort and every action.
//
// `currentUserId` exists to mirror the server's self-guard: an admin cannot
// deactivate or re-role their own account (it would be a lockout), so those
// items are simply absent from their own row instead of failing on click.
export function UserTable({
  rows,
  isLoading,
  sort,
  onSortChange,
  onEdit,
  onChangeRole,
  onDeactivate,
  onActivate,
  currentUserId,
  emptyState,
}) {
  const columns = [
    {
      // key doubles as the ?ordering= value, so it must be one of the API's
      // ordering_fields — hence first_name rather than "name".
      key: "first_name",
      header: "Name",
      sortable: true,
      render: (u) => (
        <span className="flex items-center gap-2">
          <Avatar name={u.full_name || u.email} size="sm" />
          <span className="font-medium">{u.full_name || "—"}</span>
          {u.id === currentUserId && (
            <span className="text-xs text-gray-500 dark:text-gray-400">(you)</span>
          )}
        </span>
      ),
    },
    {
      key: "email",
      header: "Email",
      sortable: true,
      render: (u) => <span className="text-gray-600 dark:text-gray-300">{u.email}</span>,
    },
    {
      key: "role",
      header: "Role",
      sortable: true,
      render: (u) => <StatusBadge map={USER_ROLE} value={u.role} />,
    },
    {
      key: "is_active",
      header: "Status",
      render: (u) => <StatusBadge map={USER_ACTIVE_STATUS} value={String(u.is_active)} />,
    },
    {
      key: "date_joined",
      header: "Added",
      sortable: true,
      render: (u) => (
        <span className="text-gray-600 dark:text-gray-300">{formatDate(u.date_joined)}</span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      className: "w-12 text-right",
      render: (u) => {
        const isSelf = u.id === currentUserId;
        const items = [
          { label: "Edit details", onClick: () => onEdit(u) },
          // Both guarded server-side for the current user; hidden here so the
          // menu only ever offers actions that can actually succeed.
          ...(isSelf ? [] : [{ label: "Change role", onClick: () => onChangeRole(u) }]),
          ...(isSelf
            ? []
            : u.is_active
              ? [{ label: "Deactivate", tone: "danger", onClick: () => onDeactivate(u) }]
              : [{ label: "Reactivate", onClick: () => onActivate(u) }]),
        ];
        return <DropdownMenu label={`Actions for ${u.full_name || u.email}`} items={items} />;
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
      emptyState={emptyState}
    />
  );
}
