import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../../components/layout/PageHeader";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { Pagination } from "../../../components/ui/Pagination";
import { SearchInput } from "../../../components/ui/SearchInput";
import { Select } from "../../../components/ui/Select";
import { CLIENT_STATUS_OPTIONS, ROLES } from "../../../lib/constants";
import { formatNumber } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { ClientForm } from "../components/ClientForm";
import { ClientTable } from "../components/ClientTable";
import { useClientMutations } from "../hooks/useClientMutations";
import { useClients } from "../hooks/useClients";

// Archetype A list page (design doc §7.3). Filters live in the URL — not
// useState — so refresh keeps them, the back button walks filter history,
// and a filtered view is a shareable link.
export function ClientListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = user?.role !== ROLES.STAFF; // UX only; the API re-checks

  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const search = searchParams.get("search") ?? "";
  const status = searchParams.get("status") ?? "";
  const ordering = searchParams.get("ordering") ?? "";

  // Only send params that are actually set — "?status=" would 400 on the
  // backend's ChoiceFilter, and clean keys keep the query cache tidy.
  const params = { page };
  if (search) params.search = search;
  if (status) params.status = status;
  if (ordering) params.ordering = ordering;

  const { data, isPending, isError, refetch } = useClients(params);
  const { remove } = useClientMutations();

  // Modal state is view state, not server state — plain useState is right here.
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingClient, setEditingClient] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    document.title = "Clients · ClientHub";
  }, []);

  function setFilter(key, value) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page"); // new filter ⇒ back to page 1
    setSearchParams(next);
  }

  const hasFilters = Boolean(search || status);

  function openCreate() {
    setEditingClient(null);
    setIsFormOpen(true);
  }

  function openEdit(client) {
    setEditingClient(client);
    setIsFormOpen(true);
  }

  function confirmDelete() {
    remove.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) });
  }

  return (
    <>
      <PageHeader
        title={data ? `Clients (${formatNumber(data.count)})` : "Clients"}
        actions={canWrite && <Button onClick={openCreate}>+ New client</Button>}
      />

      {/* Filter bar: search debounces (400 ms), selects apply instantly. */}
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchInput
          value={search}
          onDebouncedChange={(v) => setFilter("search", v)}
          placeholder="Search name, email, city, GSTIN…"
          className="w-72"
        />
        <Select
          label=""
          aria-label="Filter by status"
          options={CLIENT_STATUS_OPTIONS}
          placeholder="All statuses"
          value={status}
          onChange={(e) => setFilter("status", e.target.value)}
          className="w-40"
        />
        {hasFilters && (
          <Button variant="ghost" onClick={() => setSearchParams({})}>
            Clear
          </Button>
        )}
      </div>

      {isError ? (
        <ErrorState message="Could not load clients." onRetry={() => refetch()} />
      ) : (
        <Card padding={false}>
          <ClientTable
            rows={data?.results}
            isLoading={isPending}
            sort={ordering}
            onSortChange={(next) => setFilter("ordering", next)}
            onRowClick={(client) => navigate(`/clients/${client.id}`)}
            onEdit={openEdit}
            onDelete={setDeleteTarget}
            canWrite={canWrite}
            emptyState={
              hasFilters ? (
                <EmptyState
                  icon="🔍"
                  title="No clients match your filters"
                  action={
                    <Button variant="secondary" onClick={() => setSearchParams({})}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon="🏢"
                  title="No clients yet"
                  message="Add your first client to start tracking the relationship."
                  action={canWrite && <Button onClick={openCreate}>+ New client</Button>}
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

      <ClientForm isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} client={editingClient} />

      <ConfirmDialog
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={confirmDelete}
        isPending={remove.isPending}
        title={`Delete ${deleteTarget?.name}?`}
        message="The client will disappear from ClientHub. Its projects and history
          are kept for audit, but nobody can work on this client anymore."
      />
    </>
  );
}
