import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Badge } from "../../../components/ui/Badge";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { Select } from "../../../components/ui/Select";
import { Spinner } from "../../../components/ui/Spinner";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { Tabs } from "../../../components/ui/Tabs";
import { PRIORITY, PROJECT_STATUS, ROLES } from "../../../lib/constants";
import { formatCurrency, formatDate, formatDateTime } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { MilestoneList } from "../components/MilestoneList";
import { ProjectForm } from "../components/ProjectForm";
import { SprintList } from "../components/SprintList";
import { TaskBoard } from "../components/TaskBoard";
import { TaskDetailModal } from "../components/TaskDetailModal";
import { TaskForm } from "../components/TaskForm";
import { TeamList } from "../components/TeamList";
import { useProject } from "../hooks/useProject";
import { useProjectMutations } from "../hooks/useProjectMutations";
import { useSprints } from "../hooks/useSprints";
import { useTaskMutations } from "../hooks/useTaskMutations";

function OverviewTab({ project }) {
  const fields = [
    [
      "Client",
      project.client && (
        <Link
          to={`/clients/${project.client.id}`}
          className="text-indigo-600 hover:underline dark:text-indigo-400"
        >
          {project.client.name}
        </Link>
      ),
    ],
    ["Status", <StatusBadge key="s" map={PROJECT_STATUS} value={project.status} />],
    ["Priority", <StatusBadge key="p" map={PRIORITY} value={project.priority} />],
    ["Start date", formatDate(project.start_date)],
    ["End date", formatDate(project.end_date)],
    // `budget` is stripped from the payload for STAFF, so "absent" is normal
    // here — not an error, and not something to render as ₹0.
    ...("budget" in project
      ? [["Budget", project.budget ? formatCurrency(project.budget) : null]]
      : []),
    ["Progress", project.progress == null ? "No milestones yet" : `${project.progress}%`],
    ["Created", formatDate(project.created_at)],
    ["Last updated", formatDateTime(project.updated_at)],
  ];

  return (
    <div className="space-y-4">
      <Card>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-3">
          {fields.map(([label, value]) => (
            <div key={label}>
              <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</dt>
              <dd className="mt-0.5 text-sm text-gray-900 dark:text-gray-100">{value || "—"}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {project.description && (
        <Card title="Description">
          <p className="whitespace-pre-wrap text-sm text-gray-700 dark:text-gray-300">
            {project.description}
          </p>
        </Card>
      )}

      {project.technologies?.length > 0 && (
        <Card title="Tech stack">
          <ul className="flex flex-wrap gap-2">
            {project.technologies.map((tech) => (
              <li key={tech.id}>
                <Badge color="indigo">{tech.name}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

// The board tab owns the task modals, because every one of them is opened
// from a card. Sprint/assignee filters narrow every column at once.
function BoardTab({ project, canWrite }) {
  const { user } = useAuth();
  const { move, remove } = useTaskMutations(project.id);
  const { data: sprints } = useSprints(project.id);

  const [sprintFilter, setSprintFilter] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [openTaskId, setOpenTaskId] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  // Only send keys that are set — an empty ?sprint= would 400.
  const filters = {};
  if (sprintFilter === "backlog") filters.backlog = true;
  else if (sprintFilter) filters.sprint = sprintFilter;
  if (mineOnly && user) filters.assignee = user.id;

  const sprintOptions = [
    { value: "backlog", label: "Backlog (no sprint)" },
    ...(sprints?.map((s) => ({ value: String(s.id), label: s.name })) ?? []),
  ];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Select
          label=""
          aria-label="Filter by sprint"
          options={sprintOptions}
          placeholder="All sprints"
          value={sprintFilter}
          onChange={(e) => setSprintFilter(e.target.value)}
          className="w-56"
        />
        <Button variant={mineOnly ? "primary" : "secondary"} onClick={() => setMineOnly((v) => !v)}>
          {mineOnly ? "✓ My tasks" : "My tasks"}
        </Button>
      </div>

      <TaskBoard
        projectId={project.id}
        filters={filters}
        canWrite={canWrite}
        onOpenTask={(task) => setOpenTaskId(String(task.id))}
        onEditTask={(task) => {
          setEditingTask(task);
          setIsFormOpen(true);
        }}
        onDeleteTask={setDeleteTarget}
        onMoveTask={(id, status) => move.mutate({ id, status })}
        onCreateTask={() => {
          setEditingTask(null);
          setIsFormOpen(true);
        }}
      />

      <TaskDetailModal
        taskId={openTaskId}
        isOpen={openTaskId != null}
        onClose={() => setOpenTaskId(null)}
        canWrite={canWrite}
        onEdit={(task) => {
          setOpenTaskId(null);
          setEditingTask(task);
          setIsFormOpen(true);
        }}
      />

      <TaskForm
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        project={project}
        task={editingTask}
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
    </div>
  );
}

// Archetype C detail page (design doc §7.4): breadcrumb, summary line,
// URL-driven tabs.
export function ProjectDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = user?.role !== ROLES.STAFF; // UX only; the API re-checks

  const { data: project, isPending, isError, error, refetch } = useProject(id);
  const { remove } = useProjectMutations();

  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") ?? "overview";

  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  useEffect(() => {
    document.title = project ? `${project.name} · ClientHub` : "Projects · ClientHub";
  }, [project]);

  if (isPending) {
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );
  }

  // A soft-deleted id 404s — and so does a project STAFF are not a member of,
  // because scoping never leaks existence. Say "not found", never "no
  // permission" (§7.4).
  if (isError && error?.response?.status === 404) {
    return (
      <EmptyState
        icon="📁"
        title="Project not found"
        message="It may have been deleted, or you may not be on its team."
        action={
          <Button variant="secondary" onClick={() => navigate("/projects")}>
            Back to projects
          </Button>
        }
      />
    );
  }

  if (isError) {
    return <ErrorState message="Could not load this project." onRetry={() => refetch()} />;
  }

  const meta = [
    project.client?.name,
    project.progress != null && `${project.progress}% of milestones done`,
    `${project.members?.length ?? 0} on the team`,
    project.end_date && `due ${formatDate(project.end_date)}`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-2 text-sm text-gray-500 dark:text-gray-400">
        <Link
          to="/projects"
          className="hover:text-gray-700 hover:underline dark:hover:text-gray-200"
        >
          Projects
        </Link>{" "}
        / <span className="text-gray-900 dark:text-gray-100">{project.name}</span>
      </nav>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex flex-wrap items-center gap-3 text-2xl font-bold text-gray-900 dark:text-gray-50">
            {project.name}
            <StatusBadge map={PROJECT_STATUS} value={project.status} />
            <StatusBadge map={PRIORITY} value={project.priority} />
          </h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{meta}</p>
        </div>
        {canWrite && (
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => setIsEditOpen(true)}>
              Edit
            </Button>
            <Button variant="danger" onClick={() => setIsDeleteOpen(true)}>
              Delete
            </Button>
          </div>
        )}
      </div>

      <div className="mb-6">
        <Tabs
          tabs={[
            { key: "overview", label: "Overview" },
            { key: "board", label: "Board" },
            { key: "milestones", label: "Milestones", count: project.milestones?.length ?? 0 },
            { key: "sprints", label: "Sprints" },
            { key: "team", label: "Team", count: project.members?.length ?? 0 },
          ]}
          active={activeTab}
          onChange={(tab) => setSearchParams(tab === "overview" ? {} : { tab })}
        />
      </div>

      {activeTab === "overview" && <OverviewTab project={project} />}
      {activeTab === "board" && <BoardTab project={project} canWrite={canWrite} />}
      {activeTab === "milestones" && <MilestoneList project={project} canWrite={canWrite} />}
      {activeTab === "sprints" && <SprintList projectId={project.id} canWrite={canWrite} />}
      {activeTab === "team" && <TeamList project={project} canWrite={canWrite} />}

      <ProjectForm isOpen={isEditOpen} onClose={() => setIsEditOpen(false)} project={project} />

      <ConfirmDialog
        isOpen={isDeleteOpen}
        onClose={() => setIsDeleteOpen(false)}
        onConfirm={() => remove.mutate(project.id, { onSuccess: () => navigate("/projects") })}
        isPending={remove.isPending}
        title={`Delete ${project.name}?`}
        message="The project disappears from ClientHub along with its board. Its
          history is kept for audit, but nobody can work on it anymore."
      />
    </>
  );
}
