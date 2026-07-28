# ClientHub Frontend Design Specification

This document is the **design contract** for the React frontend. Pages are built
against these specs the same way API endpoints are built against the module docs.
Companion to `ARCHITECTURE.md` §3 (folder structure) and §7 (auth flow).

Status legend: **[built]** exists in `frontend/src` · **[next]** current phase ·
**[later]** phase 2+ module (spec exists in `docs/`, backend not built yet).

---

## 1. Design Tokens (the single source of visual truth)

Defined once, used everywhere. In Tailwind v4 these live as utilities we agree on
(documented here) — repeated patterns become components, never `@apply` soup.

### 1.1 Color

| Token | Tailwind value | Used for |
|---|---|---|
| **Primary** | `indigo-600` (hover `indigo-500`, focus ring `indigo-600`) | Primary buttons, active nav, links, focus outlines, selected states |
| Primary subtle | `indigo-50` / `indigo-100` text `indigo-700` | Active sidebar item bg, info badges |
| **Page background** | `gray-50` | The app canvas behind cards |
| **Surface** | `white` | Cards, tables, modals, topbar, sidebar |
| **Border** | `gray-200` (inputs `gray-300`) | Card borders, dividers, table rules |
| **Text primary** | `gray-900` | Headings, cell values |
| **Text secondary** | `gray-600` | Labels, descriptions, meta |
| **Text muted** | `gray-400` | Placeholders, disabled, timestamps |
| **Success** | `green-600` (badge `green-100`/`green-700`) | Won, done, active, paid |
| **Warning** | `amber-500` (badge `amber-100`/`amber-800`) | Pending, review, negotiation, due soon |
| **Danger** | `red-600` (badge `red-100`/`red-700`) | Destructive actions, errors, overdue, lost |
| **Info** | `sky-500` (badge `sky-100`/`sky-700`) | In-progress-ish intermediate states |

**Rule:** color is never the only signal (color-blind users) — every status badge
also carries its text label; errors carry an icon + message.

### 1.2 Status → color mapping (every enum in the system)

| Enum | Mapping |
|---|---|
| `Client.status` | prospect → amber · active → green · inactive → gray |
| `Lead.status` | new → indigo · contacted → sky · qualified → green · lost → gray |
| `Deal.stage` | qualified → indigo · proposal → sky · negotiation → amber · won → green · lost → red |
| `Project.status` | planned → gray · in_progress → indigo · on_hold → amber · completed → green · cancelled → red |
| `Task.status` | todo → gray · in_progress → indigo · review → amber · done → green |
| `Task.priority` | low → gray · medium → sky · high → amber · urgent → red |
| `User.role` | admin → indigo · manager → sky · staff → gray |
| `Invoice.status` [later] | draft → gray · sent → sky · partially_paid → amber · paid → green · overdue → red · cancelled → gray |
| `Ticket.status` [later] | open → indigo · in_progress → sky · waiting → amber · resolved → green · closed → gray |

These maps live in each feature's `lib/constants.js` entry as
`{ value: {label, color} }` objects consumed by `<Badge>`.

### 1.3 Typography

Font: **Inter**, fallback `ui-sans-serif, system-ui`. Data-dense app ⇒ **14 px
(`text-sm`) is the working size**, not 16.

| Style | Classes | Used for |
|---|---|---|
| Page title | `text-2xl font-bold text-gray-900` | One per page, in `PageHeader` |
| Section/card title | `text-base font-semibold text-gray-900` | Card headers, modal titles |
| Body / table cells | `text-sm text-gray-900` (secondary `text-gray-600`) | Everything |
| Label | `text-sm font-medium text-gray-700` | Form labels, table headers (`text-xs uppercase tracking-wide text-gray-500` for th) |
| Meta / caption | `text-xs text-gray-500` | Timestamps, counts, helper text |
| KPI number | `text-3xl font-semibold tracking-tight` | Dashboard tiles |

Line-length rule: free text (notes, descriptions) capped at `max-w-prose`.

### 1.4 Spacing, radius, elevation

- 4 px grid. Page gutter `px-4 sm:px-6 lg:px-8`, vertical rhythm `py-6`; gap
  between cards `gap-6`; inside cards `p-6`; dense rows `py-3`.
- Radius: `rounded-md` (6px) inputs/buttons · `rounded-lg` (8px) cards/modals ·
  `rounded-full` badges/avatars.
- Elevation: `shadow-sm` + `ring-1 ring-gray-200` cards · `shadow-md` dropdowns ·
  `shadow-xl` modals. Never more than 3 levels.

### 1.5 Motion

`transition-colors` on interactive elements (150 ms). Modals/drawers fade+scale
in 150–200 ms. **No** decorative animation; respect `prefers-reduced-motion`.

---

## 2. Breakpoints & responsive strategy

Tailwind defaults; mobile-first (base styles = phone, prefixes add up).

| Range | Layout |
|---|---|
| `< md` (phone) | Sidebar hidden → hamburger opens overlay drawer. Tables collapse to card lists (each row a stacked card showing the 3 key fields). Kanban columns horizontally scrollable with snap. Filter bar collapses into a "Filters" popover button. Modals become full-screen sheets. |
| `md–lg` (tablet) | Sidebar collapsed to icon rail (56 px, tooltips). 2-col dashboard grid. |
| `≥ lg` (desktop) | Full sidebar 256 px fixed. Content `max-w-7xl mx-auto`. 4-col KPI grid. |

Primary target is desktop (a CRM is a work tool) but every screen must be
*usable* on a phone — read, search, change a task status, add a note.

---

## 3. Accessibility floor (every page, non-negotiable)

1. Semantic landmarks: `<nav>` sidebar, `<header>` topbar, `<main>` content;
   one `<h1>` per page (in `PageHeader`); headings never skip levels.
2. Every input has a `<label htmlFor>`; errors linked via `aria-describedby`
   and announced with `role="alert"`; inputs get `aria-invalid`.
3. Full keyboard support: visible `focus-visible` ring (indigo, offset 2) on
   everything interactive; modals trap focus, close on Esc, return focus to the
   trigger; kanban cards movable via keyboard (focus card → arrow keys / menu
   with "Move to…" actions) — drag-and-drop is an enhancement, not the only way.
4. Contrast ≥ 4.5:1 for text (our gray-600-on-white and white-on-indigo-600
   pass; **never** use gray-400 for essential text).
5. Icon-only buttons get `aria-label`; decorative icons `aria-hidden`.
6. Tables: real `<table>` with `<th scope="col">`; row actions reachable by Tab.
7. Toasts use `aria-live="polite"`; destructive confirms are real dialogs.
8. Route changes move focus to the new page's `<h1>` and set `document.title`
   ("Clients · ClientHub").

---

## 4. Component inventory

### 4.1 Generic UI (`components/ui/`)

| Component | Status | API (props) | Notes |
|---|---|---|---|
| `Button` | [built] | `variant: primary·secondary·danger·ghost`, `isLoading`, `type` | default `type="button"` |
| `Input` | [built] | label, error, ...rest | |
| `Badge` | [built] | `color: gray·green·red·amber·indigo` (+ add `sky`) | |
| `Spinner` | [built] | `size` | |
| `FormField` | [next] | `label, error, required, hint, children` | wraps label + control + error; single a11y wiring point |
| `Select` | [next] | `options: [{value,label}], placeholder` | native `<select>` styled — a11y for free |
| `Textarea` | [next] | rows, ...Input API | |
| `Checkbox` | [next] | label inline | |
| `SearchInput` | [next] | `value, onDebouncedChange (400 ms), placeholder` | magnifier icon, clear button |
| `Modal` | [next] | `isOpen, onClose, title, size: sm·md·lg, children, footer` | focus trap, Esc, `aria-modal`, portal |
| `ConfirmDialog` | [next] | `title, message, confirmLabel, tone: danger·primary, isPending` | wraps Modal; used for every delete |
| `Drawer` | [next] | right-side panel, Modal semantics | quick-view without losing list context |
| `Table` | [next] | `columns: [{key, header, render?, sortable?}], rows, sort, onSortChange, onRowClick` | renders skeleton/empty/error via props |
| `Pagination` | [next] | `page, pageSize, count, onPageChange` | "Showing X–Y of Z" + prev/next + numbers |
| `Tabs` | [next] | `tabs: [{key,label,count?}], active, onChange` | URL-driven (`?tab=`), `role="tablist"` |
| `Card` | [next] | `title?, actions?, children, padding?` | white surface + ring + radius |
| `EmptyState` | [next] | `icon, title, message, action?` | every list's zero state, with CTA |
| `ErrorState` | [next] | `message, onRetry` | every query error |
| `Skeleton` / `SkeletonTable` | [next] | `rows, cols` | pulse placeholders matching final layout |
| `Toast` (+ `useToast`) | [next] | `toast.success/error(msg)` | top-right stack, 4 s auto-dismiss, `aria-live` |
| `Avatar` | [next] | `name, size` | initials on colored disc (hash of name → hue) |
| `DropdownMenu` | [next] | `trigger, items: [{label, onClick, tone?}]` | row "⋯" actions; arrow-key navigable |
| `StatusBadge` | [next] | `map, value` | Badge + a constants map; one-liner wrapper |

### 4.2 Layout (`components/layout/`)

`AppShell` [built] · `Sidebar` [built — extend with role-gated sections, mobile
drawer] · `Topbar` [built — extend with global search, notifications bell
[later], avatar menu] · `PageHeader` [built — extend with breadcrumb + actions
slot].

### 4.3 Feature components (owned by their feature folder)

`ClientTable`, `ClientForm`, `ContactList`, `LeadTable`, `LeadForm`,
`ConvertLeadDialog`, `DealBoard`, `DealCard`, `DealForm`, `ProjectTable`,
`ProjectForm`, `MemberManager`, `MilestoneList`, `TaskBoard`, `TaskCard`,
`TaskModal`, `TimeEntryList`, `LogTimeForm`, `FileUploader`, `DocumentList`,
`NoteComposer`, `ActivityTimeline`, `KpiCard` [built], chart wrappers.

---

## 5. Page archetypes (design once, reuse everywhere)

| Archetype | Skeleton | Used by |
|---|---|---|
| **A. List page** | `PageHeader(title, count, primary action)` → filter bar (`SearchInput` + `Select`s + clear) → `Card(Table)` → `Pagination`. Filters live in URL query params. | Clients, Leads, Projects, Users, Time entries, Invoices [later], Quotations [later], Tickets [later], Meetings [later] |
| **B. Board page** | `PageHeader` → filter bar → horizontal columns, one per enum value; column = header (label + count + sum) + scrollable card stack; drag-and-drop + keyboard "Move to…" | Deals (by stage), Tasks (by status, inside project) |
| **C. Detail page** | `PageHeader(breadcrumb, name, status badge, actions)` → summary strip → `Tabs` → tab panels | Client, Project, Ticket [later], Invoice [later] |
| **D. Modal/Drawer form** | `react-hook-form` + `FormField`s → footer `Cancel / Save(isLoading)`; server 400 errors mapped onto fields via `setError` | every create/edit |
| **E. Dashboard** | KPI grid → charts row → two activity lists | Dashboard, Reports [later] |
| **F. Auth page** | centered card on gray-50, logo, single form | Login |
| **G. Utility** | icon + message + action button, centered | 404, 403, ErrorBoundary crash |

Shared list-page mechanics: TanStack Query keys mirror URL
(`['clients', {page, search, status}]`), `keepPreviousData` for smooth paging,
mutations invalidate the list key, deletes always go through `ConfirmDialog`,
row click navigates to detail, "⋯" menu for edit/delete.

---

## 6. Route map

```
/login                      public                      F
/                           Dashboard                   E
/clients                    list        A     /clients/:id      detail C
/leads                      list        A     (+ convert dialog)
/deals                      board       B     (+ deal drawer)
/projects                   list        A     /projects/:id     detail C  (tabs incl. task board B)
/settings/profile           me + password
/admin/users                list        A     ADMIN only
--- later ---
/billing/invoices           A     /billing/invoices/:id   C
/quotations                 A     /tickets                A    /tickets/:id  C
/meetings                   A (+calendar view)           /reports          E
/search?q=                  global results page
*                           404 G
```

All non-login routes inside `ProtectedRoute` + `AppShell`. Sidebar order:
Dashboard · Clients · Leads · Deals · Projects · *(later: Quotations · Billing ·
Tickets · Meetings · Reports)* · — · Users (admin, `RoleGate`) · Settings.

---

## 7. Page specs

### 7.1 Login `/login` [built — verify against this spec]

Centered `max-w-sm` card: logo, "Sign in to ClientHub", email + password
(`FormField`), submit full-width `isLoading`. Errors: single generic banner
"Invalid email or password" (`role="alert"`) — never reveal which field was
wrong. Redirect authed users away from /login. No signup/forgot-password links
(admin creates users). Autofocus email; `autocomplete="email" / "current-password"`.

### 7.2 Dashboard `/`

Data: `GET /dashboard/summary/`, `GET /dashboard/charts/` (payload is
role-scoped server-side; UI renders whatever blocks arrive).

```
PageHeader: "Good morning, Meethu"  ·  date
[ KPI: Active clients ] [ Open deals + value ] [ Projects in progress ] [ My open tasks ]
[ Chart: deals by stage (funnel/bar)  ] [ Chart: tasks completed / wk (line) ]
[ List: My tasks due soon → task ]     [ List: Recent activity (timeline) ]
```

KPI card: label (gray-600 sm) + value (3xl) + delta vs last month
(green ▲ / red ▼ + `sr-only` "up/down"). Loading = 4 skeleton tiles; each card
handles its own error ("Couldn't load — Retry") so one failure doesn't blank
the page. Charts follow the dataviz rules (axis labels, no 3-D, color-blind-safe
series colors); every chart has a text alternative (title + `sr-only` summary).

### 7.3 Clients `/clients` — archetype A

Data: `['clients', {page, search, status, industry, ordering}]` ↔
`GET /clients/?search&status&industry&page&ordering`.

```
PageHeader: Clients (128)                        [+ New client]  (RoleGate M/A)
[ Search name/email/city… ] [ Status ▾ ] [ Industry ▾ ]           [ Clear ]
┌──────────────────────────────────────────────────────────────────────────┐
│ Name ⇅        Status     Industry   Acct manager   Contacts  Updated  ⋯ │
│ Acme Corp     ●Active    SaaS       MP Meethu P.   3         2d ago   ⋯ │
└──────────────────────────────────────────────────────────────────────────┘
Showing 1–20 of 128                                        ◀ 1 2 3 … 7 ▶
```

Row click → detail. "⋯" → Edit / Delete (M/A only; delete = ConfirmDialog
warning it hides the client and its projects remain). Empty state: "No clients
yet — add your first client" [+ New client]; filtered-empty: "No clients match
your filters" [Clear filters]. STAFF sees no create/edit/delete anywhere here.
`ClientForm` modal (create+edit shared): name*, industry (select), website,
email, phone, GSTIN (pattern-validated), city, status, account manager
(user select) — server 400s mapped to fields.

### 7.4 Client detail `/clients/:id` — archetype C

```
Clients / Acme Corp
Acme Corp  ●Active   SaaS · acme.com · Bengaluru        [Edit] [⋯ Delete]
AM: Meethu · 3 contacts · 2 projects · client since Mar 2026
[ Overview | Contacts (3) | Projects (2) | Documents (5) | Notes & Activity ]
```

- **Overview:** two-column def-list of all fields + mini "recent activity" (5).
- **Contacts:** card list (Avatar, name, position, email/phone links,
  ★ Primary badge) + [Add contact] modal; edit/delete per card (M/A);
  `is_primary` toggle explains "replaces current primary".
- **Projects:** slim project table filtered to this client; [+ New project]
  pre-fills client.
- **Documents:** `FileUploader` (drag-drop zone; client-side pre-checks
  size ≤ 20 MB + extension whitelist; progress bar; server remains the real
  validator) + `DocumentList` (icon by type, name, size, uploader, date,
  Download — authenticated GET, Delete own/M/A).
- **Notes & Activity:** `NoteComposer` (textarea + Save) above merged
  `ActivityTimeline` — notes (avatar + body) interleaved with system activity
  rows ("Meethu changed status: prospect → active · 2h ago"), newest first,
  "Load more" pagination.

404 from API → friendly "Client not found" state (STAFF out-of-scope objects
404 by design — never say "no permission", don't leak existence).

### 7.5 Leads `/leads` — archetype A

Columns: Company, Contact, Email, Source (badge), Status (badge), Owner,
Created, ⋯. Filters: search, status, source, owner (M/A only — STAFF is
auto-scoped to own). Row "⋯": Edit · **Convert →** (only when qualified) ·
Delete. `ConvertLeadDialog`: explains a Client will be created, pre-fills
name/contact from the lead, POST `/leads/{id}/convert/` → success toast
"Lead converted" + link to new client; converted leads show a permanent
"Converted → Acme Corp" chip and lose Convert/Delete.

### 7.6 Deals `/deals` — archetype B (pipeline board)

```
Deals · pipeline ₹42.5L                       [Board|Table]   [+ New deal]
[ Search ] [ Owner ▾ ]
┌ Qualified 4 · ₹12L ┐ ┌ Proposal 2 · ₹8L ┐ ┌ Negotiation ┐ ┌ Won ┐ ┌ Lost ┐
│ ┌────────────────┐ │
│ │ CRM revamp     │ │   card: title, client/lead name, ₹value,
│ │ Acme · ₹4.5L   │ │   expected close (red if past), owner Avatar
│ │ 30 Aug · [MP]  │ │
│ └────────────────┘ │
```

Drag between columns → optimistic `PATCH {stage}` (rollback + error toast on
failure). Keyboard: focus card → Enter opens menu with "Move to…" options.
Dropping on **Won/Lost** asks confirmation. Card click → right `Drawer` (deal
fields, linked client/lead, notes timeline, Edit). Table toggle reuses
archetype A for the same data (sortable by value/close date). STAFF sees own
deals only (server-scoped; no owner filter shown).

### 7.7 Projects `/projects` — archetype A

Columns: Name, Client, Status, Members (stacked Avatars, max 4 + "+2"),
Dates (`start → end`, end red if overdue), Budget (M/A only), ⋯.
Filters: search, status, client, member. STAFF: member-projects only,
no create/delete. `ProjectForm` modal: name*, client* (searchable select),
status, dates (end ≥ start validated), budget, description.

### 7.8 Project detail `/projects/:id` — archetype C

Header: breadcrumb, name, status badge, client link, dates, budget (M/A),
member avatars, [Edit] (M/A). Progress strip: "18/32 tasks done" + progress
bar (`role="progressbar"`).

Tabs: **Overview | Tasks | Milestones | Team | Time | Documents | Activity**

- **Tasks** (`?tab=tasks`, the heart) — archetype B board, columns
  todo / in_progress / review / done; filter bar (assignee, milestone,
  priority, search). Card: title, priority dot + label, assignee Avatar,
  due date (red overdue), milestone chip. Drag/keyboard status move →
  optimistic PATCH → server logs Activity. **STAFF can move only own tasks**
  (others' cards render without drag affordance). [+ Add task] and card
  click open **`TaskModal`** (route-driven: `?task=123` — deep-linkable,
  Esc/back closes): title, description, status, priority, assignee (project
  members only), milestone, due date; below the form: time entries list +
  [Log time] inline form (hours 0.25–24, date ≤ today, description) and the
  task's own activity trail.
- **Milestones** — checklist rows: ✓ toggle, title, due date, "6/9 tasks"
  progress; [+ Add] inline; complete-with-open-tasks asks confirmation.
- **Team** — member cards (Avatar, name, role-on-project badge, joined);
  M/A: [Add member] (user select + role), change role, remove (confirm warns
  their tasks become unassigned).
- **Time** — archetype A table (Date, Member, Task, Hours, Description) +
  footer total; filters member/date-range; M/A see all, STAFF own only.
- **Documents / Activity** — same shared components as client detail (§7.4).

### 7.9 Profile `/settings/profile`

Two cards: Profile (`GET/PATCH /auth/me/` — first/last name editable; email +
role read-only with hint "contact an admin") and Change password (current,
new ×2, client-side match check, server validators mapped; success → toast +
re-login if backend rotates tokens).

### 7.10 Users `/admin/users` — archetype A, ADMIN only (RoleGate + server)

Columns: Avatar+Name, Email, Role badge, Active, Created, ⋯. Actions: invite/
create user (modal: email*, names, role, temp password per user-management
doc), edit role, deactivate/reactivate (never delete — PROTECT on owned
clients; deactivation kills refresh tokens server-side). Deactivating yourself
is blocked in UI and server.

### 7.11 Utility pages

404 ("Page not found" + [Go to dashboard]) · 403 (RoleGate fallback) · root
`ErrorBoundary` ("Something went wrong" + [Reload]) · offline/network toast on
failed mutations.

### 7.12 Later modules — archetype mapping (no new patterns needed)

| Module (doc) | Pages | Archetypes |
|---|---|---|
| Billing (`billing-module.md`, `payments-module.md`) | invoice list · invoice detail (line items, payments, PDF) · record-payment modal | A · C · D |
| Quotations (`quotations-module.md`) | list · builder detail (items table) · send/accept states | A · C |
| Tickets (`tickets-module.md`) | list · detail w/ conversation thread | A · C + timeline |
| Meetings (`meetings-module.md`) | list + calendar toggle · schedule modal | A · D |
| Notifications (`notifications-module.md`) | topbar bell popover (unread badge, mark-read) — not a page | — |
| Reports (`reports-module.md`) | dashboard-style with date-range filter + export | E |
| Search (`search-module.md`) | topbar ⌘K palette → `/search?q=` grouped results | A variant |
| Teams (`team-management.md`) | admin list + member manager | A · D |

---

## 8. Build order (frontend Phase 2 →)

1. **Design-system sprint:** FormField, Select, Textarea, SearchInput, Modal,
   ConfirmDialog, Table, Pagination, Tabs, Card, EmptyState, ErrorState,
   Skeletons, Toast, Avatar, DropdownMenu (each demoed on a scratch route).
2. Clients list → Client form → Client detail + contacts (sets archetypes A/C/D
   for everything after).
3. Leads (+convert) → Deals board (archetype B).
4. Projects list/detail → Task board + TaskModal → milestones/team/time.
5. Documents uploader + notes/activity timeline (shared tabs).
6. Dashboard widgets → polish audit (empty/loading/error on every view,
   keyboard walkthrough, contrast check).
