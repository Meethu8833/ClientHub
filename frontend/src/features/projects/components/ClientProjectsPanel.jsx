import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { useProjects } from "../hooks/useProjects";
import { ProjectForm } from "./ProjectForm";
import { ProjectTable } from "./ProjectTable";

// The client detail page's Projects tab: the project list filtered to one
// client (?client=<id>). Read-only apart from "New project", which opens the
// normal form pre-pointed at this client — creating a project is a project
// action, so it reuses the same component rather than a second form.
export function ClientProjectsPanel({ client, canWrite }) {
  const navigate = useNavigate();
  const [isFormOpen, setIsFormOpen] = useState(false);

  const { data, isPending, isError, refetch } = useProjects({
    client: client.id,
    ordering: "-created_at",
  });

  if (isError) {
    return (
      <ErrorState message="Could not load this client's projects." onRetry={() => refetch()} />
    );
  }

  return (
    <>
      {canWrite && (
        <div className="mb-4 flex justify-end">
          <Button variant="secondary" onClick={() => setIsFormOpen(true)}>
            + New project
          </Button>
        </div>
      )}

      <Card padding={false}>
        <ProjectTable
          rows={data?.results}
          isLoading={isPending}
          onRowClick={(project) => navigate(`/projects/${project.id}`)}
          // No edit/delete here: those live on the project itself, where the
          // confirmation can say what is actually being destroyed.
          canWrite={false}
          emptyState={
            <EmptyState
              icon="📁"
              title="No projects for this client yet"
              message="Projects created here are automatically linked to this client."
              action={
                canWrite && <Button onClick={() => setIsFormOpen(true)}>+ New project</Button>
              }
            />
          }
        />
      </Card>

      <ProjectForm
        isOpen={isFormOpen}
        onClose={() => setIsFormOpen(false)}
        defaultClient={client}
      />
    </>
  );
}
