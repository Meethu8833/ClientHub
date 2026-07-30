import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/PageHeader";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { Pagination } from "../../../components/ui/Pagination";
import { SearchInput } from "../../../components/ui/SearchInput";
import { Select } from "../../../components/ui/Select";
import { ROLE_OPTIONS, USER_ACTIVE_OPTIONS } from "../../../lib/constants";
import { formatNumber } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { RoleDialog } from "../components/RoleDialog";
import { UserForm } from "../components/UserForm";
import { UserTable } from "../components/UserTable";
import { useUserMutations } from "../hooks/useUserMutations";
import { useUsers } from "../hooks/useUsers";

// Archetype A list page (design doc §7.10), admin only — the route is
// role-gated and every endpoint behind it re-checks with IsAdmin.
// Filters live in the URL so a filtered view survives refresh and is
// shareable, exactly like the clients list.
export function UserListPage() {
  const { user: currentUser } = useAuth();

  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const search = searchParams.get("search") ?? "";
  const role = searchParams.get("role") ?? "";
  const isActive = searchParams.get("is_active") ?? "";
  const ordering = searchParams.get("ordering") ?? "";

  // Only send params that are set — "?role=" would 400 on the ChoiceFilter.
  const params = { page };
  if (search) params.search = search;
  if (role) params.role = role;
  if (isActive) params.is_active = isActive;
  if (ordering) params.ordering = ordering;

  const { data, isPending, isError, refetch } = useUsers(params);
  const { deactivate, activate } = useUserMutations();

  // Modal state is view state, not server state.
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [roleTarget, setRoleTarget] = useState(null);
  const [deactivateTarget, setDeactivateTarget] = useState(null);

  useEffect(() => {
    document.title = "Users · ClientHub";
  }, []);

  function setFilter(key, value) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page"); // new filter ⇒ back to page 1
    setSearchParams(next);
  }

  const hasFilters = Boolean(search || role || isActive);

  function openCreate() {
    setEditingUser(null);
    setIsFormOpen(true);
  }

  function openEdit(target) {
    setEditingUser(target);
    setIsFormOpen(true);
  }

  function confirmDeactivate() {
    deactivate.mutate(deactivateTarget.id, { onSuccess: () => setDeactivateTarget(null) });
  }

  return (
    <>
      <PageHeader
        title={data ? `Users (${formatNumber(data.count)})` : "Users"}
        subtitle="Add managers and staff, change what they can do, and switch accounts off."
        actions={<Button onClick={openCreate}>+ New user</Button>}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchInput
          value={search}
          onDebouncedChange={(v) => setFilter("search", v)}
          placeholder="Search name or email…"
          className="w-72"
        />
        <Select
          label=""
          aria-label="Filter by role"
          options={ROLE_OPTIONS}
          placeholder="All roles"
          value={role}
          onChange={(e) => setFilter("role", e.target.value)}
          className="w-40"
        />
        <Select
          label=""
          aria-label="Filter by status"
          options={USER_ACTIVE_OPTIONS}
          placeholder="All statuses"
          value={isActive}
          onChange={(e) => setFilter("is_active", e.target.value)}
          className="w-44"
        />
        {hasFilters && (
          <Button variant="ghost" onClick={() => setSearchParams({})}>
            Clear
          </Button>
        )}
      </div>

      {isError ? (
        <ErrorState message="Could not load users." onRetry={() => refetch()} />
      ) : (
        <Card padding={false}>
          <UserTable
            rows={data?.results}
            isLoading={isPending}
            sort={ordering}
            onSortChange={(next) => setFilter("ordering", next)}
            onEdit={openEdit}
            onChangeRole={setRoleTarget}
            onDeactivate={setDeactivateTarget}
            onActivate={(target) => activate.mutate(target.id)}
            currentUserId={currentUser?.id}
            emptyState={
              hasFilters ? (
                <EmptyState
                  icon="🔍"
                  title="No users match your filters"
                  action={
                    <Button variant="secondary" onClick={() => setSearchParams({})}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon="👥"
                  title="No users yet"
                  message="Add the managers and staff who should have access to ClientHub."
                  action={<Button onClick={openCreate}>+ New user</Button>}
                />
              )
            }
          />
          {data && (
            <Pagination
              page={page}
              count={data.count}
              onPageChange={(next) => setFilter("page", String(next))}
            />
          )}
        </Card>
      )}

      <UserForm isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} user={editingUser} />

      <RoleDialog
        isOpen={roleTarget != null}
        onClose={() => setRoleTarget(null)}
        user={roleTarget}
      />

      <ConfirmDialog
        isOpen={deactivateTarget != null}
        onClose={() => setDeactivateTarget(null)}
        onConfirm={confirmDeactivate}
        isPending={deactivate.isPending}
        confirmLabel="Deactivate"
        title={`Deactivate ${deactivateTarget?.full_name || deactivateTarget?.email}?`}
        message="They are signed out everywhere and cannot sign in again until you
          reactivate them. Nothing they own is deleted, and they stay in this list."
      />
    </>
  );
}
