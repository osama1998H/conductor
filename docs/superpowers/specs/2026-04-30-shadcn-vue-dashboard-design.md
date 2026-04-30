# Dashboard redesign with shadcn-vue

**Date:** 2026-04-30
**Status:** Design — ready for implementation planning
**Branch:** `feat/dashboard-shadcn-vue` (cut from `develop`, no worktree)

## Goal

Replace the current ad-hoc Tailwind styling in `dashboard/` with shadcn-vue
primitives and a polished shell (sidebar nav, dark/light toggle, data tables).
Preserve every existing behavior; this is a visual layer change.

## Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | Full redesign: shadcn primitives + sidebar shell + page layout rework |
| 2 | Theme | Both dark and light, with system-default detection and manual toggle |
| 3 | Palette | `zinc` base, `green` accent (matches the reference screenshot) |
| 4 | Language | Stay JavaScript (no TS migration) |
| 5 | Delivery | Single branch, single PR, with logical per-page commits for review |

## Architecture

A new shell renders a persistent sidebar + header. Every existing page is
rebuilt using shadcn-vue components. Real-time data wiring (`api.js`,
`realtime.js`, `useDetailSubscription`, `useAutoPolling`, `useUserRoles`) is
preserved verbatim. Behavior parity is the bar.

### Stack additions

| Dependency | Purpose |
|---|---|
| `shadcn-vue` (CLI, dev-only) | Install + add components |
| `reka-ui` | Underlying Vue primitives shadcn-vue wraps |
| `class-variance-authority`, `clsx`, `tailwind-merge` | Variant helper (`cn()`) |
| `lucide-vue-next` | Icons (used by every shadcn component) |
| `@tanstack/vue-table` | Data tables for Jobs / DLQ |
| `vue-sonner` | Toasts (replaces `ToastHost.vue`) |
| `@vueuse/core` | `useColorMode` and small composables |

Existing deps (vue, vue-router, mermaid, tailwind v4) preserved.

### Theming

`app.css` gains shadcn-vue's CSS-variable theme block (`zinc` for `:root` and
`.dark`, `green` for `--primary` / `--ring`). The existing `--text-2xs` token
is preserved. `useColorMode` from `@vueuse/core` toggles `class="dark"` on
`<html>` with `light` / `dark` / `system` modes, persisted to `localStorage`.
A `ModeToggle.vue` exposes the choice in the header.

### Shell layout

```
┌── App.vue ─────────────────────────────────────────────┐
│ ┌─ AppSidebar ──┐ ┌─ AppHeader ─────────────────────┐  │
│ │ Conductor     │ │ <breadcrumb>   <ModeToggle> <…> │  │
│ │ ─────────     │ ├──────────────────────────────────┤ │
│ │ ▸ Overview    │ │                                  │ │
│ │ ▸ Live Feed   │ │      <router-view />             │ │
│ │ ▸ Jobs        │ │                                  │ │
│ │ ▸ DLQ         │ │                                  │ │
│ │ ▸ Schedules   │ │                                  │ │
│ │ ▸ Workers     │ │                                  │ │
│ │ ▸ Workflows   │ │                                  │ │
│ │ ─────────     │ │                                  │ │
│ │ Site: site1   │ │                                  │ │
│ └───────────────┘ └──────────────────────────────────┘ │
│ <Toaster />     <ConfirmDialog />                      │
└────────────────────────────────────────────────────────┘
```

The active route is highlighted with the green accent. The sidebar collapses
to icon-only on small viewports.

## Page-by-page conversion

| Page | Conversion |
|---|---|
| Overview | 4 NumberCards → 4 shadcn `Card`s with stat layout. 2 QueueCharts wrapped in `Card`. SVG bars kept. |
| Live Feed | Stream → `ScrollArea` of `Card` rows, `Badge` for event type. |
| Jobs | Filters → `Select` + `Input` + `Button`. List → `DataTable` (Tanstack) with sortable columns, pagination, faceted status filter. Detail panel: `Tabs` for overview/runs/args, `Card` per section. Retry/Cancel as `variant="default"` and `variant="destructive"` `Button`s. |
| DLQ | Same shape as Jobs: `DataTable` + detail. Bulk-retry uses `Checkbox` per row + sticky action bar. EditAndRetryModal → shadcn `Dialog`. |
| Schedules | `Table` (small list, no pagination), `Switch` per row for enable/disable. Detail in a right-side `Sheet` instead of split column. |
| Workers | `Table` with `Badge` + `Tooltip` for last-heartbeat exact time. |
| Workflows | Definitions in `Card` grid; runs in `Table`. |
| WorkflowRunDetail | Mermaid DAG kept inside a `Card`. Step list as `Table`. JsonViewer kept. |

## Component inventory

### Installed via shadcn-vue CLI

button, card, input, select, label, table, tabs, badge, dialog, alert-dialog,
dropdown-menu, sheet, separator, scroll-area, skeleton, switch, tooltip,
sonner, sidebar, breadcrumb, checkbox.

### Custom (kept, restyled to wrap shadcn)

- `StatusBadge` — wraps `Badge` with semantic variant prop
- `NumberCard` — wraps `Card`
- `ConfirmDialog` — wraps `AlertDialog`, same imperative API via `useConfirm`
- `EditAndRetryModal` — wraps `Dialog`
- `JsonViewer`, `MermaidDag`, `MiniCalendar`, `QueueChart` — kept as-is, light restyle if needed

### Custom (new)

- `AppSidebar.vue` — composes shadcn `Sidebar` with the seven routes
- `AppHeader.vue` — breadcrumb + ModeToggle + connection status indicator
- `ModeToggle.vue` — light/dark/system dropdown
- `JobsDataTable.vue`, `DlqDataTable.vue` — Tanstack tables

### Deleted

- `ToastHost.vue` — replaced by `<Toaster />` from `vue-sonner`

## Stores / data flow

Public contracts are preserved. Internal targets change for two stores:

- `useToast.js` — retargets internally to `vue-sonner`'s `toast()`. Call
  sites are unchanged.
- `useConfirm.js` — retargets internally to render shadcn `AlertDialog`.
  Call sites are unchanged.

New:

- `useColorMode.js` — wraps `@vueuse/core`'s `useColorMode` with our defaults.

All other composables (`useDetailSubscription`, `useAutoPolling`,
`useUserRoles`) are untouched.

## File layout (after migration)

```
dashboard/
├── components.json                  [NEW] shadcn config (tsx: false)
├── package.json                     [MODIFIED] new deps
└── src/
    ├── lib/utils.js                 [NEW] cn() helper
    ├── components/
    │   ├── ui/                      [NEW] ~25 copied shadcn .vue files
    │   ├── AppSidebar.vue           [NEW]
    │   ├── AppHeader.vue            [NEW]
    │   ├── ModeToggle.vue           [NEW]
    │   ├── JobsDataTable.vue        [NEW]
    │   ├── DlqDataTable.vue         [NEW]
    │   ├── StatusBadge.vue          [MODIFIED]
    │   ├── NumberCard.vue           [MODIFIED]
    │   ├── ConfirmDialog.vue        [MODIFIED]
    │   ├── EditAndRetryModal.vue    [MODIFIED]
    │   └── ToastHost.vue            [DELETED]
    ├── stores/
    │   ├── useColorMode.js          [NEW]
    │   ├── useToast.js              [MODIFIED] (retarget)
    │   ├── useConfirm.js            [MODIFIED] (retarget)
    │   └── (rest unchanged)
    ├── App.vue                      [MODIFIED] new shell
    ├── app.css                      [MODIFIED] shadcn theme vars
    └── pages/                       [ALL 8 MODIFIED]
```

## Verification

- `yarn build` succeeds; asset bundle lands in `conductor/public/dashboard/`
- `bench --site <site> build` then visit `/conductor-dashboard` — page renders
- Manual smoke: each page loads, retry / cancel / run-now still work,
  `ConfirmDialog` still confirms, toasts appear, real-time updates still
  arrive (verified by enqueuing a demo job via
  `bench conductor doctor --demo`)
- `claude-in-chrome` MCP screenshot pass on each page in both themes at the
  end
- No new pytest tests (UI tests aren't in scope; the Python suite is
  unaffected)

## Out of scope

- Pinia (mentioned in CLAUDE.md but not actually installed — leave the
  composable pattern as-is)
- TypeScript migration
- Chart library swap (QueueChart stays as inline SVG)
- Mermaid replacement
- Custom mobile responsive design beyond shadcn defaults
- Any feature additions (no FC compat, no Frappe Cloud, no new pages)
- Replacing the data layer (api.js, realtime.js, useDetailSubscription,
  useAutoPolling) — preserved verbatim

## Risks

- shadcn-vue `Sidebar` defines its own CSS variables — must merge with the
  existing `@theme` block in `app.css` without collision.
- `@tanstack/vue-table` adds ~30 KB gzipped; acceptable for an internal ops
  dashboard.
- shadcn-vue's CLI default writes TypeScript — must pass `tsx: false` in
  `components.json` and run with `--cwd dashboard` so files land in the right
  directory.
- Frappe's static asset serving may need `bench build` after the first
  `yarn build`; verify on first integration.

## Acceptance criteria

- All 8 pages render and behave identically to today
- Light / dark / system toggle works and persists across reloads
- Sidebar collapses properly
- `yarn build` and `bench build` produce a working `/conductor-dashboard`
- No new console errors on any page
- Existing Python test suite continues to pass unchanged
