// The API sends money as strings ("800.00") because JSON has no Decimal.
// Formatting to a display string is the frontend's job — done in one place.
const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

const int = new Intl.NumberFormat("en-IN");

export function formatCurrency(value) {
  const n = Number(value);
  return Number.isNaN(n) ? "—" : inr.format(n);
}

export function formatNumber(value) {
  return int.format(value ?? 0);
}

export function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", { dateStyle: "medium" });
}
