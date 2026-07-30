import { AreaLineChart } from "../../../components/charts/AreaLineChart";
import { ChartFrame } from "../../../components/charts/ChartFrame";
import { GroupedColumnChart } from "../../../components/charts/GroupedColumnChart";
import { StackedBar } from "../../../components/charts/StackedBar";
import { Card } from "../../../components/ui/Card";
import { ErrorState } from "../../../components/ui/ErrorState";
import { useTheme } from "../../theme/useTheme";
import { formatCurrency, formatNumber } from "../../../lib/formatters";
import {
  AGING_BUCKETS,
  chartPalette,
  compactCurrency,
  monthLabel,
  monthLabelLong,
  PROJECT_STATUS_SERIES,
} from "../../../lib/viz";
import { ChartSkeleton } from "./KpiCard";

function TicketsChart({ rows }) {
  const { isDark } = useTheme();
  const p = chartPalette(isDark);
  // Rebuilt per render (not a module constant) because the two series colours
  // differ between themes.
  const series = [
    { key: "opened", label: "Opened", color: p.seriesIndigo },
    { key: "resolved", label: "Resolved", color: p.seriesGreen },
  ];
  const data = rows.map((r) => ({
    label: monthLabel(r.month),
    fullLabel: monthLabelLong(r.month),
    opened: r.opened,
    resolved: r.resolved,
  }));

  return (
    <ChartFrame
      title="Ticket flow"
      subtitle="Opened vs resolved, last 6 months"
      legend={series}
      tableCaption="Tickets opened and resolved per month"
      tableHead={["Month", "Opened", "Resolved"]}
      tableRows={data.map((d) => [d.fullLabel, formatNumber(d.opened), formatNumber(d.resolved)])}
    >
      <GroupedColumnChart data={data} series={series} valueFormat={formatNumber} />
    </ChartFrame>
  );
}

function RevenueChart({ rows }) {
  const { isDark } = useTheme();
  const p = chartPalette(isDark);
  const data = rows.map((r) => ({
    label: monthLabel(r.month),
    fullLabel: monthLabelLong(r.month),
    value: Number(r.revenue),
    seriesLabel: "Net revenue",
  }));

  return (
    <ChartFrame
      title="Net revenue"
      subtitle="Payments received less refunds, last 12 months"
      tableCaption="Net revenue per month"
      tableHead={["Month", "Net revenue"]}
      tableRows={data.map((d) => [d.fullLabel, formatCurrency(d.value)])}
    >
      <AreaLineChart
        data={data}
        color={p.seriesIndigo}
        tickFormat={compactCurrency}
        valueFormat={formatCurrency}
      />
    </ChartFrame>
  );
}

function ProjectStatusChart({ rows }) {
  const { isDark } = useTheme();
  const p = chartPalette(isDark);
  // Render in the validated palette order, not the API's order — the ordering
  // is what keeps adjacent segments colour-blind-safe.
  const byStatus = Object.fromEntries(rows.map((r) => [r.status, r]));
  const segments = Object.entries(PROJECT_STATUS_SERIES).map(([key, entry]) => ({
    key,
    // Prefer the server's label (it owns the enum's display name); fall back
    // to ours if a new status appears before the frontend knows about it.
    label: byStatus[key]?.label ?? entry.label,
    color: p.color(entry),
    value: byStatus[key]?.count ?? 0,
  }));
  const total = segments.reduce((sum, s) => sum + s.value, 0);

  return (
    <ChartFrame
      title="Projects by status"
      subtitle={`${formatNumber(total)} ${total === 1 ? "project" : "projects"} in total`}
      tableCaption="Project count by status"
      tableHead={["Status", "Projects"]}
      tableRows={segments.map((s) => [s.label, formatNumber(s.value)])}
    >
      <StackedBar
        segments={segments}
        total={total}
        valueFormat={formatNumber}
        emptyMessage="No projects yet."
      />
    </ChartFrame>
  );
}

function AgingChart({ aging }) {
  const { isDark } = useTheme();
  const p = chartPalette(isDark);
  const segments = AGING_BUCKETS.map((entry) => ({
    key: entry.key,
    label: entry.label,
    color: p.color(entry),
    value: Number(aging[entry.key] ?? 0),
  }));
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const overdue = segments
    .filter((s) => AGING_BUCKETS.find((b) => b.key === s.key)?.overdue)
    .reduce((sum, s) => sum + s.value, 0);

  return (
    <ChartFrame
      title="Invoice aging"
      subtitle={
        total > 0
          ? `${formatCurrency(overdue)} of ${formatCurrency(total)} outstanding is overdue`
          : "Money owed, by how late it is"
      }
      tableCaption="Outstanding invoice balance by age"
      tableHead={["Age", "Balance"]}
      tableRows={segments.map((s) => [s.label, formatCurrency(s.value)])}
    >
      <StackedBar
        segments={segments}
        total={total}
        valueFormat={formatCurrency}
        emptyMessage="Nothing outstanding — every invoice is settled."
      />
    </ChartFrame>
  );
}

// The charts row. Owns its own loading/error state so a slow or failing
// charts query never blanks the KPI tiles above it.
export function ChartsSection({ query }) {
  const { data, isPending, isError, refetch } = query;

  if (isPending) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <ChartSkeleton />
        <ChartSkeleton />
      </div>
    );
  }

  if (isError) {
    return <ErrorState message="Could not load the charts." onRetry={() => refetch()} />;
  }

  const { project_status: projectStatus, tickets_by_month: ticketsByMonth } = data;
  // Absent (not zeroed) for staff — render on the data, never on a role check,
  // so the UI and the API's permissions can never disagree.
  const revenue = data.revenue_by_month;
  const aging = data.invoice_aging;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {revenue && (
        <Card className="lg:col-span-2">
          <RevenueChart rows={revenue} />
        </Card>
      )}
      <Card>
        <TicketsChart rows={ticketsByMonth} />
      </Card>
      <Card>
        <ProjectStatusChart rows={projectStatus} />
      </Card>
      {aging && (
        <Card className="lg:col-span-2">
          <AgingChart aging={aging} />
        </Card>
      )}
    </div>
  );
}
