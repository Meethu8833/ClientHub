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
import { PRIORITY_OPTIONS, ROLES, TASK_STATUS_OPTIONS } from "../../../lib/constants";
import { formatNumber } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { TaskDetailModal } from "../components/TaskDetailModal";
import { TaskForm } from "../components/TaskForm";
import { TaskTable } from "../components/TaskTable";
import { useProject } from "../hooks/useProject";
import { useProjects } from "../hooks/useProjects";
import { useTaskMutations } from "../hooks/useTaskMutations";
import { useTasks } from "../hooks/useTasks";

// TaskForm needs the PROJECT DETAIL (its members and milestones drive the
// pickers), which a cross-project row doesn't carry. Editing from this page
// therefore fetches that project first and only mounts the form once it is
// there — rendering the form early would show empty pickers and let someone
// save a task with the assignee silently cleared.
function TaskEditModal({ task, isOpen, onClose }) {
  const { data: project } = useProject(task?.project?.id ? String(task.project.id) : null, {
    enabled: isOpen,
  });
  if (!isOpen || !project) return null;
  return <TaskForm isOpen onClose={onClose} project={project} task={task} />;
}

// Cross-project task list — the "Tasks" nav item. Lives in the projects
// feature because tasks are part of the Django projects app: one feature
// folder per backend app, no matter how many nav entries it feeds.
export function TaskListPage() {
  const { user } = useAuth();
  const canWrite = user?.role !== ROLES.STAFF;

  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page")) || 1);
  const search = searchParams.get("search") ?? "";
  const status = searchParams.get("status") ?? "";
  const priority = searchParams.get("priority") ?? "";
  const project = searchParams.get("project") ?? "";
  const mine = searchParams.get("mine") === "1";
  const ordering = searchParams.get("ordering") ?? "";

  const params = { page };
  if (search) params.search = search;
  if (status) params.status = status;
  if (priority) params.priority = priority;
  if (project) params.project = project;
  if (mine && user) params.assignee = user.id;
  if (ordering) params.ordering = ordering;

  const { data, isPending, isError, refetch } = useTasks(params);
  const { move, remove } = useTaskMutations();
  // The project filter's options. 100 is the API cap; the hint says so.
  const { data: projectPage } = useProjects({ page_size: 100, ordering: "name" });

  const [openTaskId, setOpenTaskId] = useState(null);
  const [editingTask, setEditingTask] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  useEffect(() => {
    document.title = "Tasks · ClientHub";
  }, []);

  function setFilter(key, value) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setSearchParams(next);
  }

  // Mirrors the API: managers/admins may move anything they can see, STAFF
  // only the status of their own tasks.
  function canMove(task) {
    if (user?.role !== ROLES.STAFF) return true;
    return task.assignee?.id === user.id;
  }

  const hasFilters = Boolean(search || status || priority || project || mine);
  const projectOptions =
    projectPage?.results?.map((p) => ({ value: String(p.id), label: p.name })) ?? [];

  return (
    <>
      <PageHeader
        title={data ? `Tasks (${formatNumber(data.count)})` : "Tasks"}
        subtitle="Work across every project you can see. New tasks are created on a project's board."
      />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <SearchInput
          value={search}
          onDebouncedChange={(v) => setFilter("search", v)}
          placeholder="Search title, description…"
          className="w-64"
        />
        <Select
          label=""
          aria-label="Filter by project"
          options={projectOptions}
          placeholder="All projects"
          value={project}
          onChange={(e) => setFilter("project", e.target.value)}
          className="w-48"
        />
        <Select
          label=""
          aria-label="Filter by status"
          options={TASK_STATUS_OPTIONS}
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
        <Button
          variant={mine ? "primary" : "secondary"}
          onClick={() => setFilter("mine", mine ? "" : "1")}
        >
          {mine ? "✓ Assigned to me" : "Assigned to me"}
        </Button>
        {hasFilters && (
          <Button variant="ghost" onClick={() => setSearchParams({})}>
            Clear
          </Button>
        )}
      </div>

      {isError ? (
        <ErrorState message="Could not load tasks." onRetry={() => refetch()} />
      ) : (
        <Card padding={false}>
          <TaskTable
            rows={data?.results}
            isLoading={isPending}
            sort={ordering}
            onSortChange={(next) => setFilter("ordering", next)}
            onOpen={(task) => setOpenTaskId(String(task.id))}
            onEdit={setEditingTask}
            onDelete={setDeleteTarget}
            onMove={(task, next) => move.mutate({ id: task.id, status: next })}
            canWrite={canWrite}
            canMove={canMove}
            emptyState={
              hasFilters ? (
                <EmptyState
                  icon="🔍"
                  title="No tasks match your filters"
                  action={
                    <Button variant="secondary" onClick={() => setSearchParams({})}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  icon="✅"
                  title="No tasks yet"
                  message="Tasks are created on a project's board — open a project to add
                    the first one."
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

      <TaskDetailModal
        taskId={openTaskId}
        isOpen={openTaskId != null}
        onClose={() => setOpenTaskId(null)}
        canWrite={canWrite}
        onEdit={(task) => {
          setOpenTaskId(null);
          setEditingTask(task);
        }}
      />

      <TaskEditModal
        task={editingTask}
        isOpen={editingTask != null}
        onClose={() => setEditingTask(null)}
      />

      <ConfirmDialog
        isOpen={deleteTarget != null}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => remove.mutate(deleteTarget.id, { onSuccess: () => setDeleteTarget(null) })}
        isPending={remove.isPending}
        title={`Delete "${deleteTarget?.title}"?`}
        message="Its logged time goes with it. Tasks that depend on this one are
          unblocked."
      />
    </>
  );
}
