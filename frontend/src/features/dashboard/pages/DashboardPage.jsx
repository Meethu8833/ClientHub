import { Button } from "../../../components/ui/Button";
import { PageHeader } from "../../../components/layout/PageHeader";
import { formatCurrency, formatDateTime, formatNumber } from "../../../lib/formatters";
import { KpiCard, KpiCardSkeleton } from "../components/KpiCard";
import { useDashboardSummary } from "../hooks/useDashboardSummary";

function Section({ title, children }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">{title}</h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">{children}</div>
    </section>
  );
}

export function DashboardPage() {
  const { data, isPending, isError, refetch } = useDashboardSummary();

  // The three mandatory states (ARCHITECTURE §11): loading, error, data.
  if (isPending) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <Section title="Loading…">
          {Array.from({ length: 5 }, (_, i) => (
            <KpiCardSkeleton key={i} />
          ))}
        </Section>
      </>
    );
  }

  if (isError) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-700">Could not load the dashboard.</p>
          <Button variant="secondary" className="mt-3" onClick={() => refetch()}>
            Try again
          </Button>
        </div>
      </>
    );
  }

  const { clients, projects, tasks, tickets, quotations, billing, as_of: asOf } = data;

  return (
    <>
      <PageHeader title="Dashboard" subtitle={`As of ${formatDateTime(asOf)}`} />

      <Section title="My work">
        <KpiCard label="My open tasks" value={formatNumber(tasks.my_open)} />
        <KpiCard
          label="Due today"
          value={formatNumber(tasks.my_due_today)}
          tone={tasks.my_due_today > 0 ? "danger" : "default"}
        />
        <KpiCard
          label="My overdue"
          value={formatNumber(tasks.my_overdue)}
          tone={tasks.my_overdue > 0 ? "danger" : "default"}
        />
        <KpiCard label="My open tickets" value={formatNumber(tickets.my_open)} />
      </Section>

      <Section title="Clients">
        <KpiCard label="Total" value={formatNumber(clients.total)} />
        <KpiCard label="Active" value={formatNumber(clients.active)} tone="success" />
        <KpiCard label="Prospects" value={formatNumber(clients.prospect)} />
        <KpiCard label="Inactive" value={formatNumber(clients.inactive)} />
        <KpiCard label="New this month" value={formatNumber(clients.new_this_month)} />
      </Section>

      <Section title="Projects">
        <KpiCard label="Total" value={formatNumber(projects.total)} />
        <KpiCard label="In progress" value={formatNumber(projects.in_progress)} />
        <KpiCard label="Planned" value={formatNumber(projects.planned)} />
        <KpiCard label="On hold" value={formatNumber(projects.on_hold)} />
        <KpiCard
          label="Overdue"
          value={formatNumber(projects.overdue)}
          tone={projects.overdue > 0 ? "danger" : "default"}
        />
      </Section>

      <Section title="Tickets">
        <KpiCard label="Open" value={formatNumber(tickets.open)} />
        <KpiCard label="Unassigned" value={formatNumber(tickets.unassigned)} />
        <KpiCard
          label="Escalated"
          value={formatNumber(tickets.escalated)}
          tone={tickets.escalated > 0 ? "danger" : "default"}
        />
        <KpiCard
          label="SLA breached"
          value={formatNumber(tickets.sla_breached)}
          tone={tickets.sla_breached > 0 ? "danger" : "default"}
        />
      </Section>

      <Section title="Quotations">
        <KpiCard label="Draft" value={formatNumber(quotations.draft)} />
        <KpiCard label="Awaiting approval" value={formatNumber(quotations.awaiting_approval)} />
        <KpiCard label="Awaiting client" value={formatNumber(quotations.awaiting_client)} />
        <KpiCard label="Accepted this month" value={formatNumber(quotations.accepted_this_month)} />
        <KpiCard label="Pipeline value" value={formatCurrency(quotations.pipeline_value)} />
      </Section>

      {/* The API omits `billing` for staff — rendering hinges on the data,
          not on a role check, so UI and permissions can never disagree. */}
      {billing && (
        <Section title="Billing">
          <KpiCard label="Draft invoices" value={formatNumber(billing.draft)} />
          <KpiCard label="Awaiting payment" value={formatNumber(billing.awaiting_payment)} />
          <KpiCard label="Outstanding" value={formatCurrency(billing.outstanding_amount)} />
          <KpiCard
            label={`Overdue (${formatNumber(billing.overdue_count)})`}
            value={formatCurrency(billing.overdue_amount)}
            tone={billing.overdue_count > 0 ? "danger" : "default"}
          />
          <KpiCard
            label="Collected this month"
            value={formatCurrency(billing.collected_this_month)}
            tone="success"
          />
        </Section>
      )}
    </>
  );
}
