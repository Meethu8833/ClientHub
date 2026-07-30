import { Card } from "../../../components/ui/Card";
import { ErrorState } from "../../../components/ui/ErrorState";
import { Icon } from "../../../components/ui/Icon";
import { formatCurrency, formatDateTime, formatNumber } from "../../../lib/formatters";
import { useAuth } from "../../auth/useAuth";
import { ChartsSection } from "../components/DashboardCharts";
import { KpiCard, KpiCardSkeleton, StatTile } from "../components/KpiCard";
import { useDashboardCharts } from "../hooks/useDashboardCharts";
import { useDashboardSummary } from "../hooks/useDashboardSummary";

// A dashboard's job is to answer "what needs me today?" before it answers
// "how is the business doing?". So the page reads top-to-bottom as:
//
//   1. a greeting + the four HERO numbers (what needs me now)
//   2. the charts (trend and shape over time)
//   3. grouped secondary stats (the detail, folded into group cards)
//
// The previous version showed 24 identically-weighted tiles in six flat rows,
// which made the urgent ones (overdue, SLA breached) impossible to spot.

function greeting(hour) {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

// A titled panel wrapping a small grid of compact tiles.
function StatGroup({ title, children }) {
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-50">{title}</h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{children}</div>
    </Card>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const summary = useDashboardSummary();
  const charts = useDashboardCharts();
  const { data, isPending, isError, refetch } = summary;

  const now = new Date();
  const today = now.toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const firstName = user?.first_name?.trim() || user?.email?.split("@")[0] || "there";

  const header = (
    <div className="mb-6">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50">
        {greeting(now.getHours())}, {firstName}
      </h1>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
        {today}
        {data?.as_of && ` · updated ${formatDateTime(data.as_of)}`}
      </p>
    </div>
  );

  // The three mandatory states (ARCHITECTURE §11): loading, error, data.
  if (isPending) {
    return (
      <>
        {header}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <KpiCardSkeleton key={i} />
          ))}
        </div>
      </>
    );
  }

  if (isError) {
    return (
      <>
        {header}
        <ErrorState message="Could not load the dashboard." onRetry={() => refetch()} />
      </>
    );
  }

  const { clients, projects, tasks, tickets, quotations, billing } = data;

  // Attention-worthy counts, surfaced as captions so a toned tile says WHY it
  // is red rather than relying on the colour alone.
  const myLate = tasks.my_overdue;
  const ticketTrouble = tickets.sla_breached + tickets.escalated;

  return (
    <>
      {header}

      {/* 1 — the hero row: the four numbers worth acting on today. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="My open tasks"
          value={formatNumber(tasks.my_open)}
          icon={<Icon name="tasks" />}
          tone={myLate > 0 ? "danger" : "default"}
          caption={
            myLate > 0
              ? `${formatNumber(myLate)} overdue`
              : tasks.my_due_today > 0
                ? `${formatNumber(tasks.my_due_today)} due today`
                : "Nothing overdue"
          }
        />
        <KpiCard
          label="Open tickets"
          value={formatNumber(tickets.open)}
          icon={<Icon name={ticketTrouble > 0 ? "alert" : "tickets"} />}
          tone={ticketTrouble > 0 ? "danger" : "default"}
          caption={
            ticketTrouble > 0
              ? `${formatNumber(tickets.sla_breached)} past SLA · ${formatNumber(tickets.escalated)} escalated`
              : `${formatNumber(tickets.unassigned)} unassigned`
          }
        />
        <KpiCard
          label="Active projects"
          value={formatNumber(projects.in_progress)}
          icon={<Icon name="projects" />}
          tone={projects.overdue > 0 ? "danger" : "default"}
          caption={
            projects.overdue > 0
              ? `${formatNumber(projects.overdue)} past their end date`
              : `${formatNumber(projects.planned)} planned`
          }
        />
        <KpiCard
          label="Active clients"
          value={formatNumber(clients.active)}
          icon={<Icon name="clients" />}
          to="/clients"
          caption={`${formatNumber(clients.new_this_month)} new this month`}
        />
      </div>

      {/* 2 — the charts. Separate query, so slow charts never block the tiles. */}
      <div className="mt-6">
        <ChartsSection query={charts} />
      </div>

      {/* 3 — the detail, grouped so each domain reads as one thing. */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
        <StatGroup title="Clients">
          <StatTile label="Total" value={formatNumber(clients.total)} to="/clients" />
          <StatTile label="Active" value={formatNumber(clients.active)} />
          <StatTile label="Prospects" value={formatNumber(clients.prospect)} />
          <StatTile label="Inactive" value={formatNumber(clients.inactive)} />
          <StatTile label="New this month" value={formatNumber(clients.new_this_month)} />
        </StatGroup>

        <StatGroup title="Projects">
          <StatTile label="Total" value={formatNumber(projects.total)} />
          <StatTile label="In progress" value={formatNumber(projects.in_progress)} />
          <StatTile label="Planned" value={formatNumber(projects.planned)} />
          <StatTile label="On hold" value={formatNumber(projects.on_hold)} />
          <StatTile
            label="Overdue"
            value={formatNumber(projects.overdue)}
            tone={projects.overdue > 0 ? "danger" : "default"}
          />
        </StatGroup>

        <StatGroup title="Tickets">
          <StatTile label="Open" value={formatNumber(tickets.open)} />
          <StatTile label="Unassigned" value={formatNumber(tickets.unassigned)} />
          <StatTile label="Assigned to me" value={formatNumber(tickets.my_open)} />
          <StatTile
            label="Escalated"
            value={formatNumber(tickets.escalated)}
            tone={tickets.escalated > 0 ? "danger" : "default"}
          />
          <StatTile
            label="SLA breached"
            value={formatNumber(tickets.sla_breached)}
            tone={tickets.sla_breached > 0 ? "danger" : "default"}
          />
        </StatGroup>

        <StatGroup title="Quotations">
          <StatTile label="Draft" value={formatNumber(quotations.draft)} />
          <StatTile label="Awaiting approval" value={formatNumber(quotations.awaiting_approval)} />
          <StatTile label="Awaiting client" value={formatNumber(quotations.awaiting_client)} />
          <StatTile
            label="Accepted this month"
            value={formatNumber(quotations.accepted_this_month)}
          />
          <StatTile label="Pipeline value" value={formatCurrency(quotations.pipeline_value)} />
        </StatGroup>

        {/* The API omits `billing` for staff — rendering hinges on the data,
            not on a role check, so UI and permissions can never disagree. */}
        {billing && (
          <StatGroup title="Billing">
            <StatTile label="Draft invoices" value={formatNumber(billing.draft)} />
            <StatTile label="Awaiting payment" value={formatNumber(billing.awaiting_payment)} />
            <StatTile label="Outstanding" value={formatCurrency(billing.outstanding_amount)} />
            <StatTile
              label={`Overdue (${formatNumber(billing.overdue_count)})`}
              value={formatCurrency(billing.overdue_amount)}
              tone={billing.overdue_count > 0 ? "danger" : "default"}
            />
            <StatTile
              label="Collected this month"
              value={formatCurrency(billing.collected_this_month)}
              tone="success"
            />
          </StatGroup>
        )}
      </div>
    </>
  );
}
