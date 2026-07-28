import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { EmptyState } from "../../../components/ui/EmptyState";
import { ErrorState } from "../../../components/ui/ErrorState";
import { Spinner } from "../../../components/ui/Spinner";
import { StatusBadge } from "../../../components/ui/StatusBadge";
import { Tabs } from "../../../components/ui/Tabs";
import { CLIENT_STATUS, ROLES } from "../../../lib/constants";
import { formatDate, formatDateTime } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { ClientForm } from "../components/ClientForm";
import { ContactList } from "../components/ContactList";
import { useClient } from "../hooks/useClient";
import { useClientMutations } from "../hooks/useClientMutations";

// Overview tab: a definition list of every field. Rendering "—" for blanks
// (instead of hiding rows) keeps the layout stable and shows what's missing.
function OverviewTab({ client }) {
  const address = [
    client.address_line1,
    client.address_line2,
    client.city,
    client.state,
    client.postal_code,
    client.country,
  ]
    .filter(Boolean)
    .join(", ");

  const fields = [
    ["Industry", client.industry],
    [
      "Website",
      client.website && (
        <a
          href={client.website}
          target="_blank"
          rel="noreferrer"
          className="text-indigo-600 hover:underline"
        >
          {client.website}
        </a>
      ),
    ],
    [
      "Email",
      client.email && (
        <a href={`mailto:${client.email}`} className="text-indigo-600 hover:underline">
          {client.email}
        </a>
      ),
    ],
    ["Phone", client.phone],
    ["GSTIN", client.gst_number],
    ["Address", address],
    ["Account manager", client.account_manager?.name],
    ["Client since", formatDate(client.created_at)],
    ["Last updated", formatDateTime(client.updated_at)],
  ];

  return (
    <Card>
      <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-sm font-medium text-gray-500">{label}</dt>
            <dd className="mt-0.5 text-sm text-gray-900">{value || "—"}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

// Archetype C detail page (design doc §7.4): breadcrumb header, summary
// line, URL-driven tabs. Projects/Documents/Activity tabs are declared but
// disabled — they light up when those modules are built.
export function ClientDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canWrite = user?.role !== ROLES.STAFF;

  const { data: client, isPending, isError, error, refetch } = useClient(id);
  const { remove } = useClientMutations();

  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") ?? "overview";

  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);

  useEffect(() => {
    document.title = client ? `${client.name} · ClientHub` : "Clients · ClientHub";
  }, [client]);

  if (isPending) {
    return (
      <div className="flex justify-center py-20">
        <Spinner />
      </div>
    );
  }

  // A soft-deleted or unknown id 404s (and for STAFF, out-of-scope objects
  // elsewhere do too) — say "not found", never "no permission" (§7.4).
  if (isError && error?.response?.status === 404) {
    return (
      <EmptyState
        icon="🏢"
        title="Client not found"
        message="It may have been deleted, or the link is wrong."
        action={
          <Button variant="secondary" onClick={() => navigate("/clients")}>
            Back to clients
          </Button>
        }
      />
    );
  }

  if (isError) {
    return <ErrorState message="Could not load this client." onRetry={() => refetch()} />;
  }

  const meta = [
    client.industry,
    client.city,
    client.account_manager && `AM: ${client.account_manager.name}`,
    `${client.contacts.length} contact${client.contacts.length === 1 ? "" : "s"}`,
    `client since ${formatDate(client.created_at)}`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <nav aria-label="Breadcrumb" className="mb-2 text-sm text-gray-500">
        <Link to="/clients" className="hover:text-gray-700 hover:underline">
          Clients
        </Link>{" "}
        / <span className="text-gray-900">{client.name}</span>
      </nav>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-3 text-2xl font-bold text-gray-900">
            {client.name}
            <StatusBadge map={CLIENT_STATUS} value={client.status} />
          </h1>
          <p className="mt-1 text-sm text-gray-500">{meta}</p>
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
            { key: "contacts", label: "Contacts", count: client.contacts.length },
            { key: "projects", label: "Projects", disabled: true },
            { key: "documents", label: "Documents", disabled: true },
            { key: "activity", label: "Notes & Activity", disabled: true },
          ]}
          active={activeTab}
          onChange={(tab) => setSearchParams(tab === "overview" ? {} : { tab })}
        />
      </div>

      {activeTab === "overview" && <OverviewTab client={client} />}
      {activeTab === "contacts" && <ContactList client={client} canWrite={canWrite} />}

      <ClientForm isOpen={isEditOpen} onClose={() => setIsEditOpen(false)} client={client} />

      <ConfirmDialog
        isOpen={isDeleteOpen}
        onClose={() => setIsDeleteOpen(false)}
        onConfirm={() => remove.mutate(client.id, { onSuccess: () => navigate("/clients") })}
        isPending={remove.isPending}
        title={`Delete ${client.name}?`}
        message="The client will disappear from ClientHub. Its projects and history
          are kept for audit, but nobody can work on this client anymore."
      />
    </>
  );
}
