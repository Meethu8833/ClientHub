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
import { PRIORITY_OPTIONS, PROJECT_STATUS_OPTIONS, ROLES } from "../../../lib/constants";
import { formatNumber } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { ProjectForm } from "../components/ProjectForm";
import { ProjectTable } from "../components/ProjectTable";
import { useProjectMutations } from "../hooks/useProjectMutations";
import { useProjects } from "../hooks/useProjects";

// Archetype A list page (design doc §7.3), same shape as the clients list:
// filters live in the URL so refresh keeps them, back walks filter history,
// and a filtered view is a shareable link.
export function ProjectListPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = user?.role !== ROLES.STAFF; // UX only; the API re-checks

  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const search = searchParams.get("search") ?? "";
  const status = searchParams.get("status") ?? "";
  const priority = searchParams.get("priority") ?? "";
  const ordering = searchParams.get("ordering") ?? "";

  // Only send params that are actually set — "?status=" 400s on the backend's
  // ChoiceFilter, and clean keys keep the query cache tidy.
  const params = { page };
  if (search) params.search = search;
  if (status) params.status = status;
  if (priority) params.priority = priority;
  if (ordering) params.ordering = ordering;

  const { data, isPending, isError, refetch } = useProjects(params);
  const { remove } = useProjectMutations();

  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingProject, setEditingProject] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    document.title = "Projects · ClientHub";
  }, []);

  function setFilter(key, value) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page"); // new filter ⇒ back to page 1
    setSearchParams(next);
  }

  const hasFilters = Boolean(search || status || priority);

  function openCreate() {
    setEditingProject(null);
    setIsFormOpen(true);
  }

  return (
    <>
      <PageHeader
        title={data ? `Projects (${formatNumber(data.count)})` : "Projects"}
        actions={canWrite && <Button onClick={openCreate}>+ New project</Button>}
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchInput
          value={search}
          onDebouncedChange={(v) => setFilter("search", v)}
          placeholder="Search name, description, client, tech…"
          className="w-72"
        />
        <Select
          label=""
          aria-label="Filter by status"
          options={PROJECT_STATUS_OPTIONS}
          placeholder="All statuses"
          value={status}
          onChange={(e) => setFilter("status", e.target.value)}
          className="w-40"
        />
        <Select
          label=""
          aria-label="Filter by priority"
          options={PRIORITY_OPTIONS}
          placeholder="All priorities"
          value={priority}
          onChange={(e) => setFilter("priority", e.target.value)}
          className="w-40"
        />
        {hasFilters && (
          <Button variant="ghost" onClick={() => setSearchParams({})}>
            Clear
          </Button>
        )}
      </div>

      {isError ? (
        <ErrorState message="Could not load projects." onRetry={() => refetch()} />
      ) : (
        <Card padding={false}>
          <ProjectTable
            rows={data?.results}
            isLoading={isPending}
            sort={ordering}
            onSortChange={(next) => setFilter("ordering", next)}
            onRowClick={(project) => navigate(`/projects/${project.id}`)}
            onEdit={(project) => {
              setEditingProject(project);
              setIsFormOpen(true);
            }}
            onDelete={setDeleteTarget}
            canWrite={canWrite}
            emptyState={
              hasFilters ? (
                <EmptyState
                  icon="🔍"
                  title="No projects match your filters"
                  action={
                    <Button variant="secondary" onClick={() => setSearchParams({})}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon="📁"
                  title="No projects yet"
                  message={
                    canWrite
                      ? "Create a project to plan milestones and track the work."
                      : "You are not a member of any project yet — ask a manager to add you."
                  }
                  action={canWrite && <Button onClick={openCreate}>+ New project</Button>}
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

      <ProjectForm
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        project={editingProject}
      />

      <ConfirmDialog
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => remove.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })}
        isPending={remove.isPending}
        title={`Delete ${deleteTarget?.name}?`}
        message="The project disappears from ClientHub along with its board. Its
          history is kept for audit, but nobody can work on it anymore."
      />
    </>
  );
}
