# Dashboard Tailwind Migration — Design

**Date:** 2026-04-29
**Scope:** `dashboard/` (Vue 3 SPA at `/Users/osamamuhammed/frappe_15/apps/conductor/dashboard/`)
**Target:** replace ~1,150 lines of scoped CSS across 17 `.vue` files with Tailwind CSS v4 utilities and a small theme.

## Context

The Conductor dashboard is a Vue 3 + Vite SPA mounted under Frappe at `/conductor-dashboard`. Today every component owns its styling via Vue's `<style scoped>` blocks, with one global block in `App.vue` for filter-bar buttons. There is no Tailwind/PostCSS setup. The `frappe-ui` package is listed as a dependency but never imported.

The repository's CSS is utility-flavored already (class names like `mono`, `ts`, `tb`, `empty`, `error`, `filters`) and uses straightforward selectors with no `:deep()`, no CSS variables, and a single `@media` query. Most of the hard-coded color palette (`#2563eb`, `#cbd5e1`, `#94a3b8`, `#dc2626`) maps exactly to Tailwind v4 default colors.

## Decisions

| Question | Choice |
|---|---|
| Goal | **B — migration + light cleanup**: Tailwind utilities + small theme; visually equivalent to today |
| Ship strategy | **A — single PR, all 17 files at once**, atomic switch |
| Tailwind version | **v4**: CSS-first config (`@theme` block in CSS), no `tailwind.config.js`, no `postcss.config.js` |
| frappe-ui | **Remove** — currently unused, drop from `package.json` |
| Visual fidelity | **B — visually equivalent + normalized**: round odd values (e.g., `13px` → `text-sm` 14px) to Tailwind's standard scales |
| Architecture | **Approach 1 — utility-first with motion escape hatch**: zero `<style>` blocks except in `ConfirmDialog.vue` (`@keyframes`) and `ToastHost.vue` (Vue `<transition>` class names) |

## Architecture

One global stylesheet `dashboard/src/app.css` owns the Tailwind import and theme tokens. `main.js` imports it once. Vite's `@tailwindcss/vite` plugin handles the rest — no PostCSS config, no `tailwind.config.js`.

15 of 17 `.vue` files have their `<style scoped>` blocks deleted; templates use Tailwind utilities directly. The 2 motion-bearing components keep small scoped style blocks because Vue's `<transition>` class names and `@keyframes` definitions are not natural fits for utility classes.

## Theme tokens (`@theme {}` in `app.css`)

Tokens covered by Tailwind v4 defaults — no custom tokens needed:

| Old hex | Tailwind v4 default | Used for |
|---|---|---|
| `#2563eb` | `blue-600` | primary actions, active tab |
| `#1e293b` | `slate-800` | dark text |
| `#94a3b8` | `slate-400` | muted text |
| `#64748b` | `slate-500` | timestamp text |
| `#cbd5e1` | `slate-300` | borders |
| `#f8fafc` | `slate-50` | hover background |
| `#dc2626` | `red-600` | danger button |
| `#991b1b` | `red-800` | error text |
| `#eff6ff` | `blue-50` | active button |
| `#fee` | `red-50` | traceback bg |
| `#e0e7ff` | `indigo-100` | active row bg |

Custom tokens we add:

```css
@theme {
  --color-primary: var(--color-blue-600);
  --color-primary-hover: var(--color-blue-700);
  --color-danger: var(--color-red-600);

  --text-2xs: 11px;
  --text-2xs--line-height: 1rem;
}
```

Two semantic color aliases (re-skinnable via one line) and one extra font-size step for the tight table-row text. StatusBadge variants use Tailwind defaults inline (`bg-green-100 text-green-800`, etc.) — no custom badge tokens.

## File structure & build wiring

**New file:**

- `dashboard/src/app.css` — `@import "tailwindcss";` plus the `@theme {}` block from above. Nothing else; the unscoped `.filters button` block currently in `App.vue` is **deleted** (its rules become utilities applied inline on each filter-bar button — see Edge cases).

**Modified files:**

- `dashboard/src/main.js` — add `import "./app.css";` before `createApp(...)`.
- `dashboard/vite.config.js` — `import tailwindcss from "@tailwindcss/vite"` and add `tailwindcss()` to the `plugins` array.
- `dashboard/package.json` — remove `frappe-ui`, add `tailwindcss@^4` and `@tailwindcss/vite@^4` to `dependencies`. Run `yarn install` to refresh `yarn.lock`.

**Untouched:**

- `dashboard/index.html`, `dashboard/src/router.js`, `dashboard/src/api.js`, `dashboard/src/realtime.js`, `dashboard/src/stores/*` — pure logic, no styling.
- No `tailwind.config.js`, no `postcss.config.js`. v4 doesn't need them for this scope.

## Migration mapping

The patterns recur across all 17 files. Two examples cover most of them.

**Example 1 — `App.vue` tabs (active-state pattern, also used by `.subtabs` in `JobsPage.vue`):**

```html
<!-- before -->
<router-link to="/overview">Overview</router-link>

<!-- after -->
<router-link
  to="/overview"
  class="px-3 py-2 text-slate-600 border-b-2 border-transparent
         [&.router-link-active]:text-primary
         [&.router-link-active]:border-primary
         [&.router-link-active]:font-medium"
>Overview</router-link>
```

The `[&.router-link-active]:...` arbitrary-variant pattern handles vue-router's auto-applied class without any extra config.

**Example 2 — `JobsPage.vue` master-detail layout:**

```html
<div class="flex gap-4 h-[calc(100vh-100px)]">
  <div class="flex-1 min-w-0 flex flex-col">…</div>
  <div class="flex-1 min-w-0 border-l border-slate-300 pl-4 overflow-auto">…</div>
</div>
```

**Pattern rules of thumb:**

| Old CSS | Tailwind utility |
|---|---|
| `padding: 4px 8px` | `px-2 py-1` |
| `padding: 6px 8px` | `px-2 py-1.5` |
| `font-size: 11px` | `text-2xs` (custom) |
| `font-size: 12px` | `text-xs` |
| `font-size: 13px` | `text-sm` (normalized to 14px) |
| `border: 1px solid #ddd` | `border border-slate-300` |
| `background: #f8fafc` | `bg-slate-50` |
| `cursor: pointer` | `cursor-pointer` |
| `font-family: ui-monospace, ...` | `font-mono` |

**StatusBadge** keeps its component shape; the `:class` binding switches to the matching Tailwind pair (e.g., `'bg-green-100 text-green-800'` for `badge-green`).

The migration **does not touch template logic** — `v-if`, `v-for`, `@click`, computed bindings all stay. This is a pure styling rewrite.

## Edge cases

**1. App.vue unscoped `.filters button` rules (currently `App.vue:54-79`)**

These are deleted from `App.vue` and **not** moved to `app.css`. Each `<button>` in a filter bar gets the canonical utility string inline:

```
class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
       hover:border-primary hover:bg-slate-50 active:bg-blue-50
       disabled:opacity-50 disabled:cursor-not-allowed
       transition-colors duration-150"
```

There are roughly 5–7 such buttons across the 5 filter bars (`JobsPage`, `DlqPage`, `FeedPage`, `SchedulesPage`, `WorkersPage`).

**2. ConfirmDialog `@keyframes fade-in` / `pop-in`**

Stay in the component's scoped `<style>` block. ~10 lines.

**3. ToastHost Vue `<transition>` classes**

`.toast-enter-active`, `.toast-leave-active`, etc. are referenced by Vue's `<transition>` component by name. Stay in the component's scoped `<style>` block. ~8 lines.

**4. OverviewPage `@media (max-width: 768px)`**

Maps directly to Tailwind's `md:` breakpoint (default 768px). The 4-card grid becomes `grid-cols-2 md:grid-cols-4`. No custom breakpoint needed.

**5. Tailwind preflight & Mermaid**

Tailwind v4's preflight resets default browser styles. `MermaidDag.vue` renders SVG via the `mermaid` library; SVG attributes (not CSS) drive its layout, so preflight shouldn't break it. Verify visually during the manual check.

**6. Build output**

`conductor/public/dashboard/` is regenerated by `yarn build`. `emptyOutDir: true` in `vite.config.js` cleans stale artifacts.

**7. Final frappe-ui sanity check**

`grep -r "frappe-ui" dashboard/src` must return nothing before merging.

## Verification / acceptance criteria

**Build & static checks**

- `yarn install` succeeds with `frappe-ui` removed and `tailwindcss` / `@tailwindcss/vite` added
- `yarn build` produces `conductor/public/dashboard/` without errors and emits CSS from Tailwind
- `grep -r "frappe-ui" dashboard/src` returns nothing
- `grep -rn "<style" dashboard/src` returns only **2 hits** — `ConfirmDialog.vue` and `ToastHost.vue`

**Visual checks (manual, in `yarn dev`)**

- All 7 top-level routes render: Overview, Live Feed, Jobs, DLQ, Schedules, Workers, Workflows
- Tab bar: active tab is blue with bottom border; inactive tabs are slate-600
- Master-detail layout (Jobs/DLQ/Schedules/Workers): split layout, left pane scrolls, right pane scrolls independently
- Filter bars: select/input/Refresh buttons render with consistent height and spacing
- StatusBadge: green for SUCCEEDED, red for FAILED/DLQ, yellow for RUNNING/SCHEDULED_RETRY, blue for QUEUED, grey for others
- ConfirmDialog still fades in and pops in when triggered (Retry/Cancel actions)
- ToastHost notifications still slide/fade correctly
- OverviewPage at narrow widths (<768px): cards collapse from 4-col to 2-col
- MermaidDag: workflow run detail page still renders the DAG SVG

**No-regression checks**

- Browser console shows no CSS-related errors or 404s for missing assets
- Click-through smoke test: open a job, retry it, see toast; open DLQ, bulk-act on entries; navigate between routes

## Out of scope

Explicitly **not** done in this PR:

- Adopting `frappe-ui` components (Question 4 — chose A: remove)
- Visual redesign or component restructuring (Question 1 — chose B: light cleanup, not C: refresh)
- Extracting reusable Vue components for repeated table/master-detail shells (Approach 3 was rejected; YAGNI until pain felt)
- Page-by-page incremental migration (Question 2 — chose A: single PR)
- Custom design tokens beyond two semantic color aliases and one font-size step
- Touching template logic (`v-if`, `v-for`, computed properties, event handlers)
- Changes to `dashboard/src/api.js`, `realtime.js`, `router.js`, `stores/*`

## File inventory (work surface)

Files that **lose** their scoped `<style>` block entirely (15):

- `App.vue` (also loses unscoped block)
- `components/EditAndRetryModal.vue`
- `components/JsonViewer.vue`
- `components/MermaidDag.vue`
- `components/MiniCalendar.vue`
- `components/NumberCard.vue`
- `components/QueueChart.vue`
- `components/StatusBadge.vue`
- `pages/DlqPage.vue`
- `pages/FeedPage.vue`
- `pages/JobsPage.vue`
- `pages/OverviewPage.vue`
- `pages/SchedulesPage.vue`
- `pages/WorkersPage.vue`
- `pages/WorkflowRunDetailPage.vue`
- `pages/WorkflowsPage.vue`

Files that **keep** a small scoped `<style>` block (2):

- `components/ConfirmDialog.vue` — `@keyframes fade-in`, `@keyframes pop-in`
- `components/ToastHost.vue` — `.toast-enter-active`, `.toast-leave-active`, `.toast-enter-from`, `.toast-leave-to`

New files (1):

- `dashboard/src/app.css`

Modified non-Vue files (3):

- `dashboard/src/main.js`
- `dashboard/vite.config.js`
- `dashboard/package.json` (and `yarn.lock` after `yarn install`)
