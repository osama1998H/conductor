# Dashboard Tailwind Migration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ~1,150 lines of scoped CSS across 17 `.vue` files in the Conductor dashboard with Tailwind CSS v4 utilities, in a single PR, with a small theme and motion-only escape hatches in 2 components.

**Architecture:** Approach 1 from the design spec — utility-first, with a single global `app.css` containing `@import "tailwindcss";` and a `@theme {}` block (two semantic color aliases plus one custom font-size step). 15 files lose their `<style>` blocks entirely; `ConfirmDialog.vue` keeps `@keyframes`, `ToastHost.vue` keeps Vue `<transition>` class names. `frappe-ui` (currently unused) is removed.

**Tech Stack:** Vue 3 + Vite 5, Tailwind CSS v4, `@tailwindcss/vite` plugin (no `tailwind.config.js`, no `postcss.config.js`). Yarn for package management.

**Spec:** See [docs/superpowers/specs/2026-04-29-dashboard-tailwind-migration-design.md](docs/superpowers/specs/2026-04-29-dashboard-tailwind-migration-design.md).

**Note on testing discipline:** This is a styling migration — there is no programmatic unit test that verifies "the new utility classes produce visually equivalent output." Each task ends with a build-passes check + a manual visual smoke check (in `yarn dev`) on the affected route, plus a final grep-based assertion that the migration's invariants hold. Treat the visual check as the test.

---

## File Structure

**New file:**
- `dashboard/src/app.css` — global stylesheet: `@import "tailwindcss";` plus `@theme {}` block

**Modified non-Vue files:**
- `dashboard/src/main.js` — adds `import "./app.css";`
- `dashboard/vite.config.js` — adds `@tailwindcss/vite` plugin
- `dashboard/package.json` — removes `frappe-ui`, adds `tailwindcss` + `@tailwindcss/vite`

**Vue files migrated (15 lose `<style>` blocks entirely):**
- `dashboard/src/App.vue`
- `dashboard/src/components/EditAndRetryModal.vue`
- `dashboard/src/components/JsonViewer.vue`
- `dashboard/src/components/MermaidDag.vue`
- `dashboard/src/components/MiniCalendar.vue`
- `dashboard/src/components/NumberCard.vue`
- `dashboard/src/components/QueueChart.vue`
- `dashboard/src/components/StatusBadge.vue`
- `dashboard/src/pages/DlqPage.vue`
- `dashboard/src/pages/FeedPage.vue`
- `dashboard/src/pages/JobsPage.vue`
- `dashboard/src/pages/OverviewPage.vue`
- `dashboard/src/pages/SchedulesPage.vue`
- `dashboard/src/pages/WorkersPage.vue`
- `dashboard/src/pages/WorkflowRunDetailPage.vue`
- `dashboard/src/pages/WorkflowsPage.vue`

**Vue files keeping a small scoped `<style>` block (motion only):**
- `dashboard/src/components/ConfirmDialog.vue` — `@keyframes fade-in`, `@keyframes pop-in`
- `dashboard/src/components/ToastHost.vue` — `.toast-enter-active`, `.toast-leave-active`, `.toast-enter-from`, `.toast-leave-to`

---

## Working Directory

All commands assume cwd is the dashboard project:
```
/Users/osamamuhammed/frappe_15/apps/conductor/.claude/worktrees/xenodochial-wu-9c4aba/dashboard
```

---

## Task 1: Set up Tailwind v4 build wiring

**Files:**
- Create: `dashboard/src/app.css`
- Modify: `dashboard/src/main.js`
- Modify: `dashboard/vite.config.js`
- Modify: `dashboard/package.json`

- [ ] **Step 1: Remove frappe-ui and add Tailwind packages**

Run:
```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor/.claude/worktrees/xenodochial-wu-9c4aba/dashboard
yarn remove frappe-ui
yarn add tailwindcss@^4 @tailwindcss/vite@^4
```

Expected: `yarn.lock` updated, `node_modules/` populated; `package.json` no longer lists `frappe-ui` and lists `tailwindcss` + `@tailwindcss/vite` under `dependencies`.

- [ ] **Step 2: Create `dashboard/src/app.css`**

Write the file with this exact content:

```css
@import "tailwindcss";

@theme {
  --color-primary: var(--color-blue-600);
  --color-primary-hover: var(--color-blue-700);
  --color-danger: var(--color-red-600);

  --text-2xs: 11px;
  --text-2xs--line-height: 1rem;
}
```

- [ ] **Step 3: Wire `app.css` into `main.js`**

Replace the contents of `dashboard/src/main.js` with:

```js
import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import "./app.css";

createApp(App).use(router).mount("#app");
```

- [ ] **Step 4: Add the Tailwind Vite plugin to `vite.config.js`**

Replace the contents of `dashboard/vite.config.js` with:

```js
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "../conductor/public/dashboard",
    emptyOutDir: true,
    target: "es2015",
  },
});
```

- [ ] **Step 5: Verify the build works**

Run:
```bash
yarn build
```

Expected: build succeeds; `conductor/public/dashboard/` is regenerated; the emitted CSS file under `conductor/public/dashboard/assets/` contains Tailwind utility classes (e.g., grep for `\.flex\{` or `\.grid\{`).

Quick check:
```bash
grep -l "flex" ../conductor/public/dashboard/assets/*.css
```
Expected: at least one CSS file matches.

- [ ] **Step 6: Commit**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor/.claude/worktrees/xenodochial-wu-9c4aba
git add dashboard/src/app.css dashboard/src/main.js dashboard/vite.config.js dashboard/package.json dashboard/yarn.lock conductor/public/dashboard
git commit -m "feat(dashboard): wire Tailwind v4 build, remove frappe-ui

Adds @tailwindcss/vite plugin, src/app.css with @theme tokens
(--color-primary, --color-danger, --text-2xs), and main.js import.
Drops unused frappe-ui dep. No component templates touched yet."
```

---

## Task 2: Migrate `App.vue` (shell + tabs)

**Files:**
- Modify: `dashboard/src/App.vue`

- [ ] **Step 1: Replace `App.vue` with the migrated version**

Write the full file content:

```vue
<template>
  <div class="font-sans">
    <nav class="flex gap-1 border-b border-slate-200 px-4">
      <router-link
        v-for="link in navLinks"
        :key="link.to"
        :to="link.to"
        class="px-3 py-2 text-slate-600 border-b-2 border-transparent
               [&.router-link-active]:text-primary
               [&.router-link-active]:border-primary
               [&.router-link-active]:font-medium"
      >{{ link.label }}</router-link>
    </nav>
    <main class="p-4"><router-view /></main>
    <ConfirmDialog />
    <ToastHost />
  </div>
</template>

<script setup>
import ConfirmDialog from "./components/ConfirmDialog.vue";
import ToastHost from "./components/ToastHost.vue";

const navLinks = [
  { to: "/overview",  label: "Overview" },
  { to: "/feed",      label: "Live Feed" },
  { to: "/jobs",      label: "Jobs" },
  { to: "/dlq",       label: "DLQ" },
  { to: "/schedules", label: "Schedules" },
  { to: "/workers",   label: "Workers" },
  { to: "/workflows", label: "Workflows" },
];
</script>
```

Notes:
- The `<style scoped>` block (lines 23-51) and the unscoped `<style>` block (lines 54-79) are both deleted. The unscoped `.filters button` rules are not migrated to `app.css` — each filter-bar `<button>` will receive utilities inline in its own page (Tasks 9-13).
- Border color for the tab bar changes from `#ddd` to `border-slate-200` (`#e2e8f0`). This is the "B - normalized" tradeoff agreed in the spec; visually equivalent within ~1 shade.
- `font-family: system-ui, sans-serif` becomes `font-sans` (Tailwind's default `--font-sans` includes `system-ui` first).
- `nav` was repeated 7 times; consolidated into a `v-for` over `navLinks`. This is a small structural cleanup that is purely a refactor — DRY without changing behavior.

- [ ] **Step 2: Build and dev-smoke**

Run:
```bash
yarn build
```
Expected: succeeds.

Then visually smoke (manual):
```bash
yarn dev
```
- Open the app in a browser
- Verify the top nav bar renders with all 7 tabs
- Click each tab; the active one should be blue text with a blue underline
- Inactive tabs should be slate-600 text

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/App.vue
git commit -m "refactor(dashboard): migrate App.vue shell to Tailwind utilities"
```

---

## Task 3: Migrate `StatusBadge.vue`

`StatusBadge` is used by 7 files. Migrating it first means subsequent page migrations can rely on it.

**Files:**
- Modify: `dashboard/src/components/StatusBadge.vue`

- [ ] **Step 1: Replace `StatusBadge.vue` with the migrated version**

```vue
<template>
  <span :class="['text-2xs px-2 py-0.5 rounded-full font-medium', toneClasses]">{{ status }}</span>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ status: String });

const tone = computed(() => {
  switch (props.status) {
    case "SUCCEEDED": return "green";
    case "RUNNING":
    case "ALIVE": return "blue";
    case "QUEUED":
    case "SCHEDULED_RETRY": return "yellow";
    case "FAILED":
    case "DLQ":
    case "TIMED_OUT":
    case "DISPATCH_FAILED":
    case "STALE": return "red";
    case "CANCELLED":
    case "GONE": return "grey";
    default: return "grey";
  }
});

const toneClasses = computed(() => {
  switch (tone.value) {
    case "green":  return "bg-green-100 text-green-800";
    case "blue":   return "bg-blue-100 text-blue-900";
    case "yellow": return "bg-amber-100 text-amber-800";
    case "red":    return "bg-red-100 text-red-800";
    case "grey":
    default:       return "bg-slate-100 text-slate-600";
  }
});
</script>
```

Notes:
- `<style scoped>` block (lines 29-61) deleted.
- Original colors mapped: `#dcfce7/#166534` → `bg-green-100/text-green-800`; `#dbeafe/#1e40af` → `bg-blue-100/text-blue-900`; `#fef3c7/#854d0e` → `bg-amber-100/text-amber-800`; `#fee2e2/#991b1b` → `bg-red-100/text-red-800`; `#f1f5f9/#475569` → `bg-slate-100/text-slate-600`. All within 1 shade of original.
- `font-size: 11px` → `text-2xs` (custom theme token). `padding: 2px 8px` → `px-2 py-0.5`. `border-radius: 10px` → `rounded-full` (pill shape).

- [ ] **Step 2: Build and visually verify**

```bash
yarn build && yarn dev
```
Open `/jobs` (filter status=SUCCEEDED), `/dlq`, `/workers`, `/feed`. Each badge should render as a colored pill matching the old palette within 1 shade.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/StatusBadge.vue
git commit -m "refactor(dashboard): migrate StatusBadge to Tailwind utilities"
```

---

## Task 4: Migrate small leaf components (`JsonViewer`, `MermaidDag`, `NumberCard`)

Three small components, ~30 lines of style each, no shared dependencies.

**Files:**
- Modify: `dashboard/src/components/JsonViewer.vue`
- Modify: `dashboard/src/components/MermaidDag.vue`
- Modify: `dashboard/src/components/NumberCard.vue`

- [ ] **Step 1: Replace `JsonViewer.vue`**

```vue
<template>
  <pre class="font-mono text-xs bg-slate-50 p-3 rounded max-h-96 overflow-auto whitespace-pre-wrap break-words">{{ formatted }}</pre>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ value: { default: null } });

const formatted = computed(() => {
  try   { return JSON.stringify(props.value, null, 2); }
  catch { return String(props.value); }
});
</script>
```

Notes: `<style scoped>` deleted. `max-height: 400px` → `max-h-96` (384px, Tailwind step). `padding: 12px` → `p-3` (12px exact). `word-break: break-word` → `break-words`.

- [ ] **Step 2: Replace `MermaidDag.vue`'s template + remove `<style>`**

Replace the `<template>` and the `<style scoped>` block. The `<script setup>` stays exactly the same. Final file:

```vue
<script setup>
import { ref, watch, onMounted } from 'vue';
import mermaid from 'mermaid';

const props = defineProps({
  snapshot: { type: String, required: true },
  steps: { type: Array, required: true },
});

const container = ref(null);
const STATUS_COLORS = {
  PENDING: '#e5e7eb',
  READY: '#bfdbfe',
  RUNNING: '#60a5fa',
  SUCCEEDED: '#86efac',
  FAILED: '#fca5a5',
  COMPENSATED: '#fdba74',
  SKIPPED: '#d1d5db',
};

function buildMermaid() {
  if (!props.snapshot) return '';
  let topo;
  try { topo = JSON.parse(props.snapshot); }
  catch { return 'flowchart TD\nerror[invalid snapshot]'; }
  const lines = ['flowchart TD'];
  const statusByStep = {};
  for (const s of props.steps) {
    if (!s.is_compensation) statusByStep[s.step_id] = s.status;
  }
  for (const step of topo.steps) {
    const status = statusByStep[step.name] || 'PENDING';
    lines.push(`  ${step.name}["${step.name}"]`);
    lines.push(`  style ${step.name} fill:${STATUS_COLORS[status] || '#e5e7eb'}`);
  }
  for (const step of topo.steps) {
    for (const dep of step.depends_on) {
      lines.push(`  ${dep} --> ${step.name}`);
    }
  }
  return lines.join('\n');
}

async function render() {
  if (!container.value) return;
  const code = buildMermaid();
  const { svg } = await mermaid.render('wf-dag', code);
  container.value.innerHTML = svg;
}

onMounted(() => {
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
  render();
});
watch(() => [props.snapshot, props.steps], render, { deep: true });
</script>

<template>
  <div ref="container" class="flex justify-center py-4" />
</template>
```

Notes: `<style scoped>` deleted. `padding: 16px 0` → `py-4` (16px). `STATUS_COLORS` map stays in JS — those are inline SVG `fill` attributes set by mermaid, not Tailwind classes.

- [ ] **Step 3: Replace `NumberCard.vue`**

```vue
<template>
  <div
    class="bg-white border border-slate-200 rounded-md px-5 py-4 cursor-pointer
           min-h-20 flex flex-col justify-between
           transition-colors duration-150 hover:border-primary"
    @click="$emit('click')"
  >
    <div class="text-3xl font-semibold text-slate-800">{{ value }}</div>
    <div class="text-xs text-slate-500 uppercase tracking-wider">{{ label }}</div>
  </div>
</template>

<script setup>
defineProps({
  value: { type: [Number, String], default: 0 },
  label: { type: String, required: true },
});
defineEmits(["click"]);
</script>
```

Notes: `<style scoped>` deleted. `padding: 16px 20px` → `px-5 py-4`. `font-size: 28px` → `text-3xl` (30px, normalized per spec Q5-B). `letter-spacing: 0.5px` → `tracking-wider` (0.05em, close to 0.5px at typical font sizes).

- [ ] **Step 4: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/overview`: 4 NumberCards render with values, hover should turn the border blue
- Open a job's detail (`/jobs/<id>`, then click "Args" tab): JsonViewer renders args as monospace JSON in a slate background
- Open a workflow run (`/workflows`, click a run): MermaidDag renders the SVG DAG centered

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/JsonViewer.vue dashboard/src/components/MermaidDag.vue dashboard/src/components/NumberCard.vue
git commit -m "refactor(dashboard): migrate JsonViewer, MermaidDag, NumberCard to Tailwind"
```

---

## Task 5: Migrate `MiniCalendar.vue` and `QueueChart.vue`

Two visualization components.

**Files:**
- Modify: `dashboard/src/components/MiniCalendar.vue`
- Modify: `dashboard/src/components/QueueChart.vue`

- [ ] **Step 1: Replace `MiniCalendar.vue`**

```vue
<template>
  <div class="grid grid-cols-7 gap-0.5 max-w-80">
    <div v-for="(d, i) in DOW" :key="i" class="text-center text-[10px] text-slate-400 p-1">{{ d }}</div>
    <div
      v-for="cell in cells"
      :key="cell.iso"
      :class="[
        'aspect-square p-1 rounded-sm relative bg-slate-50',
        cell.fires > 0 && 'bg-blue-100',
        cell.iso === todayISO && 'outline outline-1 outline-primary',
      ]"
    >
      <span class="text-2xs text-slate-600">{{ cell.day }}</span>
      <span
        v-if="cell.fires > 0"
        class="absolute bottom-1 right-1 w-1.5 h-1.5 bg-primary rounded-full"
        :title="`${cell.fires} fires`"
      ></span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ fires: { type: Array, default: () => [] } });

const DOW = ["S", "M", "T", "W", "T", "F", "S"];
const todayISO = new Date().toISOString().slice(0, 10);

const cells = computed(() => {
  const out = [];
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - today.getDay());
  for (let i = 0; i < 28; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = d.toISOString().slice(0, 10);
    const fires = props.fires.filter(f => String(f).startsWith(iso)).length;
    out.push({ iso, day: d.getDate(), fires });
  }
  return out;
});
</script>
```

Notes: `<style scoped>` deleted. `font-size: 10px` → arbitrary `text-[10px]` (no native step). `font-size: 11px` → `text-2xs` (custom token). `width/height: 6px` → `w-1.5 h-1.5`. `outline` shorthand replaced with explicit `outline outline-1 outline-primary`.

- [ ] **Step 2: Replace `QueueChart.vue`**

```vue
<template>
  <div class="bg-white border border-slate-200 rounded-md p-4">
    <div class="text-sm font-medium text-slate-600 mb-3">{{ title }}</div>
    <div v-if="!data.length" class="text-slate-400 p-4 text-center text-xs">No data</div>
    <div v-else>
      <div
        v-for="row in data"
        :key="row.label"
        class="grid grid-cols-[100px_1fr_50px] gap-3 items-center py-1 text-xs"
      >
        <div class="text-slate-600 overflow-hidden text-ellipsis whitespace-nowrap">{{ row.label }}</div>
        <div class="bg-slate-100 h-3.5 rounded-sm overflow-hidden">
          <div
            class="bg-primary h-full transition-[width] duration-300"
            :style="{ width: pct(row.value) + '%' }"
          ></div>
        </div>
        <div class="text-right text-slate-800 font-medium">{{ row.value }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({
  title: { type: String, default: "" },
  data: { type: Array, default: () => [] },
});

const max = computed(() => Math.max(1, ...props.data.map(d => d.value || 0)));
function pct(v) { return Math.max(0, Math.min(100, ((v || 0) / max.value) * 100)); }
</script>
```

Notes: `<style scoped>` deleted. `grid-template-columns: 100px 1fr 50px` → arbitrary `grid-cols-[100px_1fr_50px]`. `height: 14px` → `h-3.5` (14px exact). `transition: width 0.3s` → `transition-[width] duration-300`.

- [ ] **Step 3: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/overview`: QueueChart renders two charts (queue depth + DLQ counts) with bars animating on data updates
- Open a schedule's detail (`/schedules/<name>`): MiniCalendar renders 4 weeks with today outlined and fire dots on relevant days

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/MiniCalendar.vue dashboard/src/components/QueueChart.vue
git commit -m "refactor(dashboard): migrate MiniCalendar, QueueChart to Tailwind"
```

---

## Task 6: Migrate `ConfirmDialog.vue` (keeps `@keyframes`)

`@keyframes fade-in` and `pop-in` stay in scoped CSS. Everything else becomes utilities.

**Files:**
- Modify: `dashboard/src/components/ConfirmDialog.vue`

- [ ] **Step 1: Replace `ConfirmDialog.vue`**

```vue
<template>
  <div
    v-if="state.open"
    class="fixed inset-0 bg-slate-900/45 flex items-center justify-center z-[200] confirm-fade-in"
    @click.self="onCancel"
  >
    <div class="bg-white rounded-lg px-6 pt-5 pb-4 min-w-[360px] max-w-[520px]
                shadow-[0_20px_48px_rgba(15,23,42,0.25)] confirm-pop-in">
      <h3 v-if="state.title" class="m-0 mb-2 text-[15px] font-semibold text-slate-900">{{ state.title }}</h3>
      <p class="m-0 mb-4 text-sm text-slate-700 leading-relaxed">{{ state.message }}</p>
      <div class="flex justify-end gap-2">
        <button
          class="px-4 py-1.5 text-sm rounded font-medium bg-white border border-slate-300 text-slate-600
                 hover:bg-slate-50 hover:border-slate-400
                 transition-colors duration-100 cursor-pointer"
          @click="onCancel"
        >{{ state.cancelText }}</button>
        <button
          :class="[
            'px-4 py-1.5 text-sm rounded font-medium border text-white cursor-pointer',
            'transition-colors duration-100',
            state.danger
              ? 'bg-danger border-danger hover:bg-red-700'
              : 'bg-primary border-primary hover:bg-primary-hover',
          ]"
          @click="onOk"
        >
          {{ state.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount } from "vue";
import { useConfirmState, _resolve } from "../stores/useConfirm";

const state = useConfirmState();

function onOk() {
  _resolve(true);
}
function onCancel() {
  _resolve(false);
}

function handleKey(e) {
  if (!state.value.open) return;
  if (e.key === "Escape") onCancel();
  if (e.key === "Enter") onOk();
}
onMounted(() => window.addEventListener("keydown", handleKey));
onBeforeUnmount(() => window.removeEventListener("keydown", handleKey));
</script>

<style scoped>
.confirm-fade-in {
  animation: fade-in 0.12s ease;
}

.confirm-pop-in {
  animation: pop-in 0.14s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes pop-in {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}
</style>
```

Notes:
- `bg-slate-900/45` → semi-transparent backdrop matching `rgba(15, 23, 42, 0.45)`.
- `bg-primary-hover` references the custom theme alias `--color-primary-hover`.
- The two `confirm-fade-in` / `confirm-pop-in` classes are minimal scoped CSS that wires the `@keyframes` to the elements. Total scoped CSS: ~14 lines.
- Box shadow uses arbitrary value `shadow-[0_20px_48px_rgba(15,23,42,0.25)]` since the existing shadow is non-standard.
- `padding: 20px 24px 16px` → `px-6 pt-5 pb-4` (24/20/16 — exact).
- `font-size: 15px` (title) → arbitrary `text-[15px]` (no native step between 14px and 16px).

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/jobs`, click a row, click "Retry" — confirm dialog should fade in + pop in
- Press Esc → dialog dismisses; click Cancel → dialog dismisses; click Retry → action runs
- Open `/dlq`, select an entry, click "Discard" — danger variant should show red OK button

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/ConfirmDialog.vue
git commit -m "refactor(dashboard): migrate ConfirmDialog to Tailwind, keep @keyframes"
```

---

## Task 7: Migrate `ToastHost.vue` (keeps Vue `<transition>` classes)

Vue's `<transition-group name="toast">` injects `.toast-enter-active`, `.toast-leave-active`, `.toast-enter-from`, `.toast-leave-to` by name. Those stay in scoped CSS. Everything else becomes utilities.

**Files:**
- Modify: `dashboard/src/components/ToastHost.vue`

- [ ] **Step 1: Replace `ToastHost.vue`**

```vue
<template>
  <div class="fixed top-4 right-4 z-[300] flex flex-col gap-2 pointer-events-none">
    <transition-group name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        :class="[
          'bg-white border border-slate-300 border-l-4 rounded',
          'px-3.5 py-2.5 text-sm text-slate-800',
          'shadow-[0_4px_12px_rgba(15,23,42,0.12)]',
          'min-w-60 max-w-[420px] pointer-events-auto',
          toneClasses(t.type),
        ]"
      >
        {{ t.message }}
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import { useToasts } from "../stores/useToast";
const toasts = useToasts();

function toneClasses(type) {
  switch (type) {
    case "success": return "border-l-green-600";
    case "error":   return "border-l-danger bg-red-50 text-red-800";
    case "warning": return "border-l-orange-600";
    default:        return "border-l-primary";
  }
}
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: transform 0.16s ease, opacity 0.16s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
```

Notes:
- The `<style scoped>` block is trimmed from 51 lines to 11 lines — only the Vue transition classes remain.
- `border-left: 4px solid X` becomes `border-l-4` + `border-l-X` (Tailwind's directional border-color shorthand).
- `padding: 10px 14px` → `px-3.5 py-2.5` (14px / 10px — exact).
- `font-size: 13px` → `text-sm` (14px — normalized per spec Q5-B).
- `min-width: 240px` → `min-w-60` (240px exact).

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/jobs`, click a row, click "Retry" → success toast slides in from the right, fades in, persists, then auto-dismisses
- Trigger a failure path (e.g., retry an already-running job) → red toast with red-50 background

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/ToastHost.vue
git commit -m "refactor(dashboard): migrate ToastHost to Tailwind, keep transition classes"
```

---

## Task 8: Migrate `EditAndRetryModal.vue`

Modal with form fields. No motion to preserve.

**Files:**
- Modify: `dashboard/src/components/EditAndRetryModal.vue`

- [ ] **Step 1: Replace `EditAndRetryModal.vue`**

```vue
<template>
  <div
    class="fixed inset-0 bg-black/40 flex items-center justify-center z-[100]"
    @click.self="$emit('cancel')"
  >
    <div class="bg-white rounded-md p-5 min-w-[480px] max-w-[720px] max-h-[80vh] overflow-auto">
      <h3 class="mt-0">Edit &amp; retry — {{ entryName }}</h3>
      <p class="text-xs text-slate-500 mb-4">JSON-validated on save. Edited payload must remain JSON-native.</p>

      <label class="block text-xs font-medium mt-2 mb-1">args (JSON array)</label>
      <textarea
        v-model="argsText"
        rows="5"
        class="w-full font-mono text-xs p-2 border border-slate-300 rounded"
      ></textarea>
      <label class="block text-xs font-medium mt-2 mb-1">kwargs (JSON object)</label>
      <textarea
        v-model="kwargsText"
        rows="10"
        class="w-full font-mono text-xs p-2 border border-slate-300 rounded"
      ></textarea>

      <div v-if="error" class="text-red-800 my-2">{{ error }}</div>

      <div class="flex justify-end gap-2 mt-4">
        <button
          class="px-3.5 py-1.5 border border-slate-300 bg-white rounded cursor-pointer
                 disabled:opacity-60 disabled:cursor-not-allowed"
          @click="$emit('cancel')"
        >Cancel</button>
        <button
          class="px-3.5 py-1.5 bg-primary text-white border border-primary rounded cursor-pointer
                 disabled:opacity-60 disabled:cursor-not-allowed"
          @click="onSave"
          :disabled="saving"
        >{{ saving ? "Saving…" : "Save & retry" }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { api } from "../api";

const props = defineProps({
  entryName: { type: String, required: true },
  initialArgs: { type: Array, default: () => [] },
  initialKwargs: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["cancel", "saved"]);

const argsText = ref(JSON.stringify(props.initialArgs, null, 2));
const kwargsText = ref(JSON.stringify(props.initialKwargs, null, 2));
const error = ref("");
const saving = ref(false);

async function onSave() {
  error.value = "";
  let parsedArgs, parsedKwargs;
  try { parsedArgs = JSON.parse(argsText.value); } catch { error.value = "args is not valid JSON"; return; }
  try { parsedKwargs = JSON.parse(kwargsText.value); } catch { error.value = "kwargs is not valid JSON"; return; }

  saving.value = true;
  try {
    const newId = await api.dlqEditAndRetry(props.entryName, JSON.stringify(parsedArgs), JSON.stringify(parsedKwargs));
    emit("saved", newId);
  } catch (e) {
    error.value = e.message || "Save failed";
  } finally {
    saving.value = false;
  }
}
</script>
```

Notes: `<style scoped>` block (lines 56-133) deleted. `padding: 6px 14px` → `px-3.5 py-1.5` (exact). `padding: 8px` (textarea) → `p-2` (exact).

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/dlq`, select a JSON-safe entry (status=PENDING_REVIEW, payload `is_json_safe`), click "Edit & retry…" — modal opens with two textareas pre-filled with the JSON
- Click outside → cancel; click Cancel → cancel; corrupt the JSON and click Save → red error message appears

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/EditAndRetryModal.vue
git commit -m "refactor(dashboard): migrate EditAndRetryModal to Tailwind"
```

---

## Task 9: Migrate `OverviewPage.vue`

Smallest page. Establishes the responsive grid pattern (Tailwind's `md:` breakpoint).

**Files:**
- Modify: `dashboard/src/pages/OverviewPage.vue`

- [ ] **Step 1: Replace `OverviewPage.vue`**

```vue
<template>
  <div class="px-2">
    <div v-if="!state" class="p-6 text-center text-slate-400">Loading…</div>
    <div v-else>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <NumberCard :value="totalDepth" label="Total queue depth" @click="go('/jobs')" />
        <NumberCard :value="aliveWorkers" label="Active workers" @click="go('/workers')" />
        <NumberCard :value="dlqPending" label="DLQ pending review" @click="go('/dlq')" />
        <NumberCard :value="schedulesEnabled" label="Schedules enabled" @click="go('/schedules')" />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <QueueChart title="Queue depth by queue" :data="queueDepthData" />
        <QueueChart title="DLQ status counts" :data="dlqData" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "../stores/useDashboardState";
import NumberCard from "../components/NumberCard.vue";
import QueueChart from "../components/QueueChart.vue";

const router = useRouter();
const { state } = useAutoPolling();

const totalDepth = computed(() =>
  (state.value?.queues || []).reduce((sum, q) => sum + (q.depth_redis || 0), 0)
);
const aliveWorkers = computed(() => state.value?.worker_summary?.alive ?? 0);
const dlqPending = computed(() => state.value?.dlq_summary?.pending_review ?? 0);
const schedulesEnabled = computed(() => state.value?.schedule_summary?.enabled_count ?? 0);

const queueDepthData = computed(() =>
  (state.value?.queues || []).map(q => ({ label: q.name, value: q.depth_redis }))
);

const dlqData = computed(() => {
  const s = state.value?.dlq_summary || {};
  return [
    { label: "Pending", value: s.pending_review || 0 },
    { label: "Retried", value: s.retried || 0 },
    { label: "Discarded", value: s.discarded || 0 },
  ];
});

function go(path) { router.push(path); }
</script>
```

Notes: `<style scoped>` deleted. The `@media (max-width: 768px)` rule that switched 4-col → 2-col is replaced with mobile-first `grid-cols-2 md:grid-cols-4` (Tailwind's `md:` breakpoint defaults to 768px — same threshold). Charts move from always-2-col to `grid-cols-1 md:grid-cols-2` for the same reason.

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/overview` at full width → 4 cards across, 2 charts across
- Resize browser narrower than 768px → 2 cards across (2 rows), 1 chart per row

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/OverviewPage.vue
git commit -m "refactor(dashboard): migrate OverviewPage to Tailwind"
```

---

## Task 10: Migrate `FeedPage.vue`

**Files:**
- Modify: `dashboard/src/pages/FeedPage.vue`

- [ ] **Step 1: Replace `FeedPage.vue`**

```vue
<template>
  <div class="px-2">
    <div class="flex gap-4 items-center mb-4">
      <h2 class="m-0">Live Feed</h2>
      <label class="flex gap-1 items-center text-sm text-slate-600 cursor-pointer">
        <input type="checkbox" v-model="paused" /> Pause updates
      </label>
      <span class="text-xs text-slate-400">{{ paused ? "(showing snapshot)" : `(updating; ${rows.length} jobs)` }}</span>
    </div>

    <div class="max-h-[calc(100vh-180px)] overflow-y-auto">
      <div
        v-for="row in rows"
        :key="row.job_id"
        class="flex gap-3 items-center px-3 py-2 border-b border-slate-200 cursor-pointer text-sm hover:bg-slate-50"
        @click="open(row.job_id)"
      >
        <span class="font-mono text-2xs text-slate-500 min-w-[140px]">{{ formatTime(row.enqueued_at) }}</span>
        <StatusBadge :status="row.status" />
        <span class="text-xs text-slate-600 min-w-20">{{ row.queue }}</span>
        <code class="font-mono text-xs flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{{ row.method }}</code>
        <span class="font-mono text-2xs text-slate-400">{{ row.job_id.slice(0, 8) }}…</span>
      </div>
      <div v-if="!rows.length" class="p-6 text-center text-slate-400">No jobs yet.</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "../stores/useDashboardState";
import StatusBadge from "../components/StatusBadge.vue";

const router = useRouter();
const { state } = useAutoPolling();

const paused = ref(false);
const frozenRows = ref([]);

function formatTime(ts) {
  if (!ts) return "";
  return String(ts).replace("T", " ").slice(0, 19);
}

const rows = computed(() => {
  if (paused.value) return frozenRows.value;
  return state.value?.feed_recent || [];
});

watch(paused, (now) => {
  if (now) frozenRows.value = [...(state.value?.feed_recent || [])];
});

function open(id) { router.push({ path: `/jobs/${id}` }); }
</script>
```

Notes: `<style scoped>` deleted. The redundant `class="job-id mono"` (which had both `font-size: 11px color: #94a3b8` and `font-family: ui-monospace`) collapses into `font-mono text-2xs text-slate-400`.

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/feed` → live feed renders, jobs appear as polling fires
- Click a row → navigate to `/jobs/<id>`
- Toggle "Pause updates" → feed freezes; uncheck → updates resume

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/FeedPage.vue
git commit -m "refactor(dashboard): migrate FeedPage to Tailwind"
```

---

## Task 11: Migrate `JobsPage.vue` (master-detail pattern)

The largest and most complex page. Establishes the master-detail layout pattern reused by DLQ/Schedules/Workers.

**Files:**
- Modify: `dashboard/src/pages/JobsPage.vue`

- [ ] **Step 1: Replace `JobsPage.vue`**

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="flex gap-2 mb-3">
        <select
          v-model="filters.status"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        >
          <option value="">All statuses</option>
          <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
        </select>
        <input
          v-model="filters.method"
          placeholder="method contains…"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        />
        <input
          v-model="filters.queue"
          placeholder="queue"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        />
        <button
          @click="reload"
          class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
                 hover:border-primary hover:bg-slate-50 active:bg-blue-50
                 disabled:opacity-50 disabled:cursor-not-allowed
                 transition-colors duration-150 cursor-pointer"
        >Refresh</button>
      </div>

      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Status</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Method</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Queue</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Attempt</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Enqueued</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.job_id"
            :class="[
              'cursor-pointer hover:bg-slate-50',
              row.job_id === job_id && 'bg-indigo-100',
            ]"
            @click="open(row.job_id)"
          >
            <td class="px-2 py-1.5 border-b border-slate-200">
              <StatusBadge :status="row.status" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 font-mono">{{ row.method }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">{{ row.queue }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">{{ row.attempt }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 text-2xs text-slate-500">{{ row.enqueued_at }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="!rows.length" class="text-slate-400 p-3 text-center">No jobs match.</div>
    </div>

    <div class="flex-1 min-w-0 border-l border-slate-200 pl-4 overflow-auto" v-if="job_id">
      <div v-if="!detail" class="text-slate-400 p-3 text-center">Loading…</div>
      <div v-else>
        <header class="flex gap-2 items-center mb-3 flex-wrap">
          <StatusBadge :status="detail.status" />
          <code class="font-mono">{{ detail.method }}</code>
          <span>· attempt {{ detail.attempt }}/{{ detail.max_attempts }}</span>
          <span>· queue {{ detail.queue }}</span>
        </header>

        <nav class="flex gap-1 border-b border-slate-200 mb-3">
          <button
            v-for="t in ['overview', 'runs', 'args']"
            :key="t"
            :class="[
              'px-2.5 py-1.5 bg-transparent border-0 border-b-2 cursor-pointer',
              subtab === t ? 'border-primary text-primary' : 'border-transparent',
            ]"
            @click="subtab = t"
          >{{ t === 'runs' ? `Runs (${detail.runs?.length || 0})` : t.charAt(0).toUpperCase() + t.slice(1) }}</button>
        </nav>

        <section v-if="subtab === 'overview'">
          <p v-if="detail.last_error_message" class="text-red-800">
            {{ detail.last_error_type }}: {{ detail.last_error_message }}
          </p>
          <details v-if="detail.last_traceback">
            <summary>Traceback</summary>
            <pre class="font-mono text-2xs bg-red-50 p-2 rounded max-h-96 overflow-auto">{{ detail.last_traceback }}</pre>
          </details>
          <div class="mt-4 flex gap-2">
            <button
              @click="onRetry"
              :disabled="!canRetry"
              class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer
                     disabled:bg-slate-300 disabled:cursor-not-allowed"
            >Retry</button>
            <button
              @click="onCancel"
              :disabled="!canCancel"
              class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer
                     disabled:bg-slate-300 disabled:cursor-not-allowed"
            >Cancel</button>
          </div>
        </section>

        <section v-if="subtab === 'runs'">
          <table class="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th class="text-left px-2 py-1 border-b border-slate-200">#</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Status</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Started</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Finished</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Duration</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Error</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in (detail.runs || [])" :key="r.attempt_number">
                <td class="px-2 py-1 border-b border-slate-200">{{ r.attempt_number }}</td>
                <td class="px-2 py-1 border-b border-slate-200">
                  <StatusBadge :status="r.status" />
                </td>
                <td class="px-2 py-1 border-b border-slate-200 text-2xs text-slate-500">{{ r.started_at }}</td>
                <td class="px-2 py-1 border-b border-slate-200 text-2xs text-slate-500">{{ r.finished_at }}</td>
                <td class="px-2 py-1 border-b border-slate-200">{{ r.duration_ms }}ms</td>
                <td class="px-2 py-1 border-b border-slate-200">{{ r.error_type }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="subtab === 'args'">
          <h4>args</h4>
          <JsonViewer :value="detail.args_decoded" />
          <h4>kwargs</h4>
          <JsonViewer :value="detail.kwargs_decoded" />
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList } from "../api";
import { useDetailSubscription } from "../stores/useDetailSubscription";
import { useUserRoles } from "../stores/useUserRoles";
import { confirm } from "../stores/useConfirm";
import { toast } from "../stores/useToast";
import StatusBadge from "../components/StatusBadge.vue";
import JsonViewer from "../components/JsonViewer.vue";

const props = defineProps({ job_id: String });
const router = useRouter();
const { job_id } = toRefs(props);

const STATUSES = [
  "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DLQ",
  "TIMED_OUT", "SCHEDULED_RETRY", "CANCELLED", "DISPATCH_FAILED",
];

const filters = reactive({ status: "", method: "", queue: "" });
const rows = ref([]);
const subtab = ref("overview");

async function reload() {
  const f = {};
  if (filters.status) f.status = filters.status;
  if (filters.queue) f.queue = filters.queue;
  if (filters.method) f.method = ["like", `%${filters.method}%`];
  rows.value = await getList("Conductor Job", {
    fields: ["job_id", "method", "queue", "status", "attempt", "enqueued_at", "last_error_message"],
    filters: f,
    order_by: "enqueued_at desc",
    limit: 50,
  });
}

watch(filters, reload, { deep: true, immediate: true });

function open(id) {
  router.push({ path: `/jobs/${id}` });
}

const { data: detail, refetch: refetchDetail } = useDetailSubscription(
  "Conductor Job",
  "conductor:job",
  job_id,
  () => api.getJob(job_id.value),
);

const { isOperator } = useUserRoles();

const canRetry = computed(() =>
  isOperator &&
  ["FAILED", "TIMED_OUT", "DLQ", "CANCELLED", "DISPATCH_FAILED"].includes(detail.value?.status)
);

const canCancel = computed(() =>
  isOperator &&
  ["QUEUED", "RUNNING", "SCHEDULED_RETRY"].includes(detail.value?.status)
);

async function onRetry() {
  if (!(await confirm(`Retry job ${job_id.value.slice(0, 8)}…?`,
                       { title: "Retry job", confirmText: "Retry" }))) return;
  try {
    const newId = await api.retryJob(job_id.value);
    toast(`Re-enqueued as ${newId.slice(0, 8)}…`, "success");
    reload();
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
  }
}

async function onCancel() {
  if (!(await confirm(`Cancel job ${job_id.value.slice(0, 8)}…?`,
                       { title: "Cancel job", confirmText: "Cancel job",
                         cancelText: "Keep running", danger: true }))) return;
  await api.cancelJob(job_id.value);
  toast("Job cancellation requested", "info");
  refetchDetail();
}
</script>
```

Notes:
- `<style scoped>` block (lines 195-346) deleted.
- The 3 subtab buttons are consolidated into a `v-for` over `['overview', 'runs', 'args']` — small DRY cleanup.
- Filter `<button>` gets the canonical filter-button utility string from the spec.
- Action buttons keep blue primary styling; disabled state goes slate-300.
- `border: 1px solid #ddd` (left border on detail) → `border-slate-200` (#e2e8f0, 1 shade off — within Q5-B tolerance).
- `header` is a tag selector in old CSS — replaced with a `<header class="flex gap-2 ...">` element with utilities directly.

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/jobs` → table renders with filters at top, rows clickable
- Click a job → detail pane slides in on the right with subtabs
- Click each subtab (Overview/Runs/Args) → content switches
- Filter by status, by queue, by method substring → table updates
- Active row should be highlighted indigo-100
- Hover on rows → slate-50 background

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/JobsPage.vue
git commit -m "refactor(dashboard): migrate JobsPage to Tailwind (master-detail pattern)"
```

---

## Task 12: Migrate `DlqPage.vue`

Master-detail like JobsPage, plus a bulk-action bar and edit modal trigger.

**Files:**
- Modify: `dashboard/src/pages/DlqPage.vue`

- [ ] **Step 1: Replace `DlqPage.vue`'s `<template>` and delete the `<style>` block**

The `<script setup>` block (lines 106-261) stays exactly the same — do not edit it. Replace only the `<template>` (lines 1-104) and delete the `<style scoped>` block (lines 263-433). New template:

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="flex gap-2 mb-3">
        <select
          v-model="filters.status"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        >
          <option value="">All statuses</option>
          <option value="PENDING_REVIEW">Pending review</option>
          <option value="RETRIED">Retried</option>
          <option value="DISCARDED">Discarded</option>
        </select>
        <input
          v-model="filters.queue"
          placeholder="queue"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        />
        <button
          @click="reload"
          class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
                 hover:border-primary hover:bg-slate-50 active:bg-blue-50
                 disabled:opacity-50 disabled:cursor-not-allowed
                 transition-colors duration-150 cursor-pointer"
        >Refresh</button>
      </div>

      <div v-if="selected.size > 0" class="flex gap-2 items-center p-2 bg-slate-100 rounded mb-2 text-sm">
        <span>{{ selected.size }} selected</span>
        <button
          @click="onRetry"
          :disabled="!isOperator"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs
                 disabled:bg-slate-300 disabled:cursor-not-allowed"
        >Retry</button>
        <button
          v-if="isSysMgr"
          @click="onDiscard"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs"
        >Discard</button>
        <button
          v-if="isSysMgr && selected.size === 1 && currentSafe"
          @click="onOpenEdit"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs"
        >Edit &amp; retry…</button>
        <button
          @click="clearSelection"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs"
        >Clear</button>
      </div>

      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-slate-200"></th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Queue</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Status</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Attempts</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Last error</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Moved at</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.name"
            :class="row.name === entry_name && 'bg-indigo-100'"
          >
            <td class="px-2 py-1.5 border-b border-slate-200">
              <input type="checkbox" :checked="selected.has(row.name)" @change="toggleSelect(row.name)" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">{{ row.queue }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">
              <StatusBadge :status="row.status" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">{{ row.attempts }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer font-mono" @click="open(row.name)">{{ row.last_error_type }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer text-2xs text-slate-500" @click="open(row.name)">{{ row.moved_at }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="text-slate-400 p-3 text-center">No DLQ entries match.</div>
    </div>

    <div class="flex-1 min-w-0 border-l border-slate-200 pl-4 overflow-auto" v-if="entry_name">
      <div v-if="!detailEntry" class="text-slate-400 p-3 text-center">Loading…</div>
      <div v-else>
        <header class="flex gap-2 items-center mb-3 flex-wrap">
          <StatusBadge :status="detailEntry.status" />
          <span>· queue {{ detailEntry.queue }}</span>
          <span>· attempts {{ detailEntry.attempts }}</span>
          <span class="text-2xs text-slate-500">{{ detailEntry.moved_at }}</span>
        </header>

        <section class="mt-4">
          <h4 class="mb-2">Last error</h4>
          <p class="text-red-800">{{ detailEntry.last_error_type }}: {{ detailEntry.last_error_message }}</p>
          <details v-if="detailEntry.last_traceback">
            <summary>Traceback</summary>
            <pre class="font-mono text-2xs bg-red-50 p-2 rounded max-h-96 overflow-auto">{{ detailEntry.last_traceback }}</pre>
          </details>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">
            Original payload
            <span
              :class="[
                'text-2xs px-1.5 py-0.5 rounded ml-2',
                detailEntry.is_json_safe ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800',
              ]"
            >
              {{ detailEntry.is_json_safe ? "JSON-safe ✓" : "non-JSON types — edit-and-retry not available" }}
            </span>
          </h4>
          <h5 class="my-2 mb-1 text-xs text-slate-500">args</h5>
          <JsonViewer :value="detailEntry.payload_decoded?.args" />
          <h5 class="my-2 mb-1 text-xs text-slate-500">kwargs</h5>
          <JsonViewer :value="detailEntry.payload_decoded?.kwargs" />
        </section>

        <section v-if="detailEntry.job" class="mt-4">
          <h4 class="mb-2">Linked job</h4>
          <router-link :to="`/jobs/${detailEntry.job}`">{{ detailEntry.job }}</router-link>
        </section>

        <section v-if="detailEntry.reviewed_by" class="mt-4">
          <h4 class="mb-2">Review</h4>
          <p>by <code class="font-mono">{{ detailEntry.reviewed_by }}</code> at <span class="text-2xs text-slate-500">{{ detailEntry.reviewed_at }}</span></p>
          <p v-if="detailEntry.review_notes">{{ detailEntry.review_notes }}</p>
        </section>

        <div class="mt-4 flex gap-2">
          <button
            @click="onRetrySingle"
            :disabled="!isOperator"
            class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer
                   disabled:bg-slate-300 disabled:cursor-not-allowed"
          >Retry as-is</button>
          <button
            v-if="isSysMgr"
            @click="onDiscardSingle"
            class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer"
          >Discard</button>
          <button
            v-if="isSysMgr && detailEntry.is_json_safe"
            @click="onOpenEditSingle"
            class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer"
          >Edit &amp; retry…</button>
        </div>
      </div>
    </div>

    <EditAndRetryModal
      v-if="editing"
      :entryName="editing.name"
      :initialArgs="editing.args"
      :initialKwargs="editing.kwargs"
      @cancel="editing = null"
      @saved="onEditSaved"
    />
  </div>
</template>
```

Notes:
- The original `.bulk-bar` background `#f1f5f9` → `bg-slate-100` (exact match).
- `.safety.safe` (`#dcfce7/#166534`) → `bg-green-100/text-green-800`; `.safety.unsafe` (`#fef3c7/#854d0e`) → `bg-amber-100/text-amber-800`.

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/dlq` → table renders with status filter defaulting to PENDING_REVIEW
- Check checkboxes on rows → bulk-bar appears with action buttons
- Click a row body (not the checkbox) → detail pane opens
- Click "Edit & retry…" on a JSON-safe entry → modal opens; cancel closes it
- Verify JSON-safe / unsafe pills render in green / amber

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/DlqPage.vue
git commit -m "refactor(dashboard): migrate DlqPage to Tailwind"
```

---

## Task 13: Migrate `SchedulesPage.vue`

Master-detail with calendar widget, fires list, recent runs table.

**Files:**
- Modify: `dashboard/src/pages/SchedulesPage.vue`

- [ ] **Step 1: Replace `SchedulesPage.vue`'s `<template>` and delete the `<style>` block**

The `<script setup>` block (lines 107-201) stays exactly the same. Replace only `<template>` (lines 1-105) and delete `<style scoped>` (lines 203-329). New template:

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="flex gap-2 mb-3">
        <input
          v-model="filters.q"
          placeholder="search name…"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        />
        <button
          @click="reload"
          class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
                 hover:border-primary hover:bg-slate-50 active:bg-blue-50
                 disabled:opacity-50 disabled:cursor-not-allowed
                 transition-colors duration-150 cursor-pointer"
        >Refresh</button>
      </div>
      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Name</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Cron</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">TZ</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Enabled</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Next run</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Last status</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.name"
            :class="row.name === name && 'bg-indigo-100'"
          >
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer font-mono" @click="open(row.name)">{{ row.name }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer font-mono" @click="open(row.name)">{{ row.cron_expression }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">{{ row.timezone }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">
              <input type="checkbox" :checked="!!row.enabled" :disabled="!isSysMgr" @change="onToggleEnabled(row)" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer text-2xs text-slate-500" @click="open(row.name)">{{ row.next_run_at }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">
              <StatusBadge v-if="row.last_status" :status="row.last_status" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200">
              <button
                :disabled="!isOperator"
                @click="onRunNow(row.name)"
                title="Dispatches now; cron cadence is unaffected."
                class="px-2 py-0.5 bg-primary text-white border-0 rounded text-2xs cursor-pointer
                       disabled:bg-slate-300 disabled:cursor-not-allowed"
              >Run now</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="text-slate-400 p-3 text-center">No schedules.</div>
    </div>

    <div class="flex-1 min-w-0 border-l border-slate-200 pl-4 overflow-auto" v-if="name">
      <div v-if="!schedule" class="text-slate-400 p-3 text-center">Loading…</div>
      <div v-else>
        <header class="flex gap-3 items-center mb-4 flex-wrap">
          <h3>{{ schedule.name }}</h3>
          <code class="font-mono">{{ schedule.cron_expression }}</code>
          <span>· {{ schedule.timezone }}</span>
          <input type="checkbox" :checked="!!schedule.enabled" :disabled="!isSysMgr"
            @change="onToggleEnabled(schedule)" />
        </header>

        <section class="mt-4">
          <h4 class="mb-2">Last dispatch</h4>
          <p v-if="schedule.last_status">
            <StatusBadge :status="schedule.last_status" /> at <span class="text-2xs text-slate-500">{{ schedule.last_run_at }}</span>
          </p>
          <p v-else>(never dispatched)</p>
        </section>

        <section v-if="schedule.last_job" class="mt-4">
          <h4 class="mb-2">Last job</h4>
          <p>
            <router-link :to="`/jobs/${schedule.last_job}`">{{ schedule.last_job }}</router-link>
            <StatusBadge v-if="lastJobStatus" :status="lastJobStatus" />
          </p>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Next 10 fires</h4>
          <ul class="list-none p-0 m-0 text-xs">
            <li v-for="f in nextFires" :key="f" class="py-0.5 text-2xs text-slate-500">{{ f }}</li>
          </ul>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Calendar</h4>
          <MiniCalendar :fires="nextFires" />
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Recent runs (heuristic by method)</h4>
          <table class="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th class="text-left px-2 py-1 border-b border-slate-200">Job ID</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Status</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Enqueued</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in recentRuns" :key="r.job_id">
                <td class="px-2 py-1 border-b border-slate-200">
                  <router-link :to="`/jobs/${r.job_id}`" class="font-mono">{{ r.job_id.slice(0, 8) }}…</router-link>
                </td>
                <td class="px-2 py-1 border-b border-slate-200">
                  <StatusBadge :status="r.status" />
                </td>
                <td class="px-2 py-1 border-b border-slate-200 text-2xs text-slate-500">{{ r.enqueued_at }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </div>
  </div>
</template>
```

Notes: The `.fires` list (`list-style: none; padding: 0; margin: 0`) becomes `list-none p-0 m-0`. The `<li>` `padding: 2px 0` becomes `py-0.5`.

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/schedules` → schedule table renders
- Click a row → detail pane shows cron expression, last dispatch, next 10 fires, calendar (with today outlined), recent runs
- Toggle "Enabled" checkbox → state persists (assuming sysmgr role)
- Click "Run now" → confirm dialog → toast on success

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/SchedulesPage.vue
git commit -m "refactor(dashboard): migrate SchedulesPage to Tailwind"
```

---

## Task 14: Migrate `WorkersPage.vue`

Master-detail; nearly identical patterns to JobsPage.

**Files:**
- Modify: `dashboard/src/pages/WorkersPage.vue`

- [ ] **Step 1: Replace `WorkersPage.vue`'s `<template>` and delete the `<style>` block**

The `<script setup>` block (lines 96-171) stays exactly the same. Replace only `<template>` (lines 1-94) and delete `<style scoped>` (lines 173-268). New template:

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="mb-3">
        <button
          @click="reload"
          class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
                 hover:border-primary hover:bg-slate-50 active:bg-blue-50
                 disabled:opacity-50 disabled:cursor-not-allowed
                 transition-colors duration-150 cursor-pointer"
        >Refresh</button>
      </div>
      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Status</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Worker</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Host</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">PID</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Queues</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">HB age</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in sortedRows"
            :key="row.name"
            :class="[
              'cursor-pointer hover:bg-slate-50',
              row.name === worker_id && 'bg-indigo-100',
            ]"
            @click="open(row.name)"
          >
            <td class="px-2 py-1.5 border-b border-slate-200">
              <StatusBadge :status="row.status" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 font-mono">{{ row.name }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">{{ row.host }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">{{ row.pid }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">{{ parseQueues(row.queues) }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 text-2xs text-slate-500">{{ heartbeatAge(row.last_heartbeat) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="text-slate-400 p-3 text-center">No workers registered.</div>
    </div>

    <div class="flex-1 min-w-0 border-l border-slate-200 pl-4 overflow-auto" v-if="worker_id">
      <div v-if="!detail" class="text-slate-400 p-3 text-center">Loading…</div>
      <div v-else>
        <header class="flex gap-2 items-center mb-4 flex-wrap">
          <StatusBadge :status="detail.status" />
          <code class="font-mono">{{ detail.name }}</code>
          <span>· {{ detail.host }}:{{ detail.pid }}</span>
          <span v-if="detail.conductor_version">· v{{ detail.conductor_version }}</span>
        </header>

        <section class="mt-4">
          <h4 class="mb-2">Queues</h4>
          <p class="font-mono">{{ parseQueues(detail.queues) }}</p>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Heartbeat</h4>
          <p>Last beat at <span class="text-2xs text-slate-500">{{ detail.last_heartbeat }}</span> ({{ detail.heartbeat_age_seconds }}s ago)</p>
          <p>Started at <span class="text-2xs text-slate-500">{{ detail.started_at }}</span></p>
        </section>

        <section v-if="detail.current_job" class="mt-4">
          <h4 class="mb-2">Currently executing</h4>
          <router-link :to="`/jobs/${detail.current_job}`" class="font-mono">{{ detail.current_job }}</router-link>
          <span v-if="currentJobStatus"> ·
            <StatusBadge :status="currentJobStatus" />
          </span>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Recent jobs handled</h4>
          <table v-if="detail.recent_jobs?.length" class="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th class="text-left px-2 py-1 border-b border-slate-200">Job ID</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Method</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Queue</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Status</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Finished</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in detail.recent_jobs" :key="r.job_id">
                <td class="px-2 py-1 border-b border-slate-200">
                  <router-link :to="`/jobs/${r.job_id}`" class="font-mono">{{ r.job_id.slice(0, 8) }}…</router-link>
                </td>
                <td class="px-2 py-1 border-b border-slate-200 font-mono">{{ r.method }}</td>
                <td class="px-2 py-1 border-b border-slate-200">{{ r.queue }}</td>
                <td class="px-2 py-1 border-b border-slate-200">
                  <StatusBadge :status="r.status" />
                </td>
                <td class="px-2 py-1 border-b border-slate-200 text-2xs text-slate-500">{{ r.finished_at }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="text-slate-400 p-3 text-center">No recent jobs.</div>
        </section>
      </div>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/workers` → table sorted alive-first
- Click a worker → detail pane shows host:pid, heartbeat info, current job (if any), recent jobs

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/WorkersPage.vue
git commit -m "refactor(dashboard): migrate WorkersPage to Tailwind"
```

---

## Task 15: Migrate `WorkflowsPage.vue` and `WorkflowRunDetailPage.vue`

Two small pages that share workflow domain.

**Files:**
- Modify: `dashboard/src/pages/WorkflowsPage.vue`
- Modify: `dashboard/src/pages/WorkflowRunDetailPage.vue`

- [ ] **Step 1: Replace `WorkflowsPage.vue`**

```vue
<script setup>
import { ref, onMounted } from 'vue';
import { listWorkflows, listWorkflowRuns } from '../api.js';
import { useAutoPolling } from '../stores/useDashboardState.js';
import StatusBadge from '../components/StatusBadge.vue';

const workflows = ref([]);
const recentRuns = ref([]);
const selectedWorkflow = ref(null);

async function refresh() {
  workflows.value = await listWorkflows();
  recentRuns.value = await listWorkflowRuns({
    workflow: selectedWorkflow.value,
    limit: 50,
  });
}

useAutoPolling();
onMounted(refresh);

function selectWorkflow(name) {
  selectedWorkflow.value = name;
  refresh();
}
</script>

<template>
  <div>
    <h2>Workflows</h2>
    <table class="w-full border-collapse mb-6">
      <thead>
        <tr>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Name</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Version</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Active</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">24h</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Last Bump</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="w in workflows"
          :key="w.workflow_name"
          :class="[
            'cursor-pointer hover:bg-slate-50',
            selectedWorkflow === w.workflow_name && 'bg-yellow-100',
          ]"
          @click="selectWorkflow(w.workflow_name)"
        >
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ w.workflow_name }}</td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">v{{ w.version }}</td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ w.active_runs }}</td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ w.recent_runs_24h }}</td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ w.last_version_bumped_at || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <h3 v-if="selectedWorkflow">Runs of {{ selectedWorkflow }}</h3>
    <h3 v-else>Recent Runs (all workflows)</h3>
    <table class="w-full border-collapse mb-6">
      <thead>
        <tr>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Run ID</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Workflow</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Status</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Started</th>
          <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Finished</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in recentRuns" :key="r.name">
          <td class="px-2.5 py-1.5 border-b border-slate-200">
            <router-link :to="`/workflows/runs/${r.name}`">{{ r.name }}</router-link>
          </td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ r.workflow }} (v{{ r.definition_version }})</td>
          <td class="px-2.5 py-1.5 border-b border-slate-200"><StatusBadge :status="r.status" /></td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ r.started_at || '—' }}</td>
          <td class="px-2.5 py-1.5 border-b border-slate-200">{{ r.finished_at || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
```

Notes: `<style scoped>` deleted. `background: #fef9c3` (active row) → `bg-yellow-100` (`#fef9c3` is exactly Tailwind's `yellow-100`). `background: #f9fafb` (hover) → `bg-slate-50` (`#f8fafc` — 1 shade off; within Q5-B tolerance).

- [ ] **Step 2: Replace `WorkflowRunDetailPage.vue`**

```vue
<script setup>
import { useRouter } from 'vue-router';
import { useUserRoles } from '../stores/useUserRoles.js';
import { computed, toRefs } from 'vue';
import { getWorkflowRun, cancelWorkflowRun } from '../api.js';
import { useDetailSubscription } from '../stores/useDetailSubscription.js';
import MermaidDag from '../components/MermaidDag.vue';
import StatusBadge from '../components/StatusBadge.vue';

const props = defineProps({ run_id: String });
const router = useRouter();
const { run_id } = toRefs(props);

const { data, refetch: refetchData } = useDetailSubscription(
  'Conductor Workflow Run',
  'conductor:workflow_run',
  run_id,
  () => getWorkflowRun(run_id.value),
);

const { isOperator, isSysMgr } = useUserRoles();
const canCancel = computed(() =>
  data.value && data.value.run && data.value.run.status === 'RUNNING' && (isOperator.value || isSysMgr.value)
);

async function cancel() {
  await cancelWorkflowRun(run_id.value);
  await refetchData();
}
</script>

<template>
  <div v-if="data && data.run">
    <header class="flex items-center gap-3 mb-4">
      <button
        @click="router.back()"
        class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
               hover:border-primary hover:bg-slate-50 cursor-pointer"
      >&laquo; Back</button>
      <h2>{{ data.run.name }}</h2>
      <div class="flex items-center gap-3">
        <strong>Workflow:</strong> {{ data.run.workflow }} (v{{ data.run.definition_version }})
        <StatusBadge :status="data.run.status" />
        <button
          v-if="canCancel"
          @click="cancel"
          class="px-3 py-1.5 bg-red-500 text-white border-0 rounded cursor-pointer"
        >Cancel run</button>
      </div>
    </header>

    <section>
      <h3>DAG</h3>
      <MermaidDag :snapshot="data.snapshot" :steps="data.steps" />
    </section>

    <section>
      <h3>Step runs</h3>
      <table class="w-full border-collapse">
        <thead>
          <tr>
            <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Step</th>
            <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Type</th>
            <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Status</th>
            <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Started</th>
            <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Finished</th>
            <th class="text-left px-2.5 py-1.5 border-b border-slate-200">Job</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in data.steps" :key="s.name">
            <td class="px-2.5 py-1.5 border-b border-slate-200">{{ s.step_id }}</td>
            <td class="px-2.5 py-1.5 border-b border-slate-200">{{ s.is_compensation ? 'compensation' : 'forward' }}</td>
            <td class="px-2.5 py-1.5 border-b border-slate-200"><StatusBadge :status="s.status" /></td>
            <td class="px-2.5 py-1.5 border-b border-slate-200">{{ s.started_at || '—' }}</td>
            <td class="px-2.5 py-1.5 border-b border-slate-200">{{ s.finished_at || '—' }}</td>
            <td class="px-2.5 py-1.5 border-b border-slate-200">
              <router-link v-if="s.job" :to="`/jobs/${s.job}`">{{ s.job }}</router-link>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="data.run.last_error">
      <h3>Last error</h3>
      <pre class="bg-slate-100 p-3 overflow-x-auto">{{ data.run.last_error }}</pre>
    </section>
  </div>
</template>
```

Notes: `<style scoped>` deleted. `background: #ef4444` (cancel-btn) → `bg-red-500` (exact). `background: #f3f4f6` (pre) → `bg-slate-100` (close enough; `#f3f4f6` is Tailwind's `gray-100`, `#f1f5f9` is `slate-100`). The original cancel-btn lacks any padding direction differentiation — original `padding: 6px 12px` → `px-3 py-1.5`.

- [ ] **Step 3: Build and verify**

```bash
yarn build && yarn dev
```
- Open `/workflows` → workflows table renders; click a workflow → row highlights yellow, runs list reloads
- Click a run → workflow run detail page opens with DAG (Mermaid SVG), step runs table, cancel button (only if RUNNING + operator/sysmgr)

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/WorkflowsPage.vue dashboard/src/pages/WorkflowRunDetailPage.vue
git commit -m "refactor(dashboard): migrate Workflows pages to Tailwind"
```

---

## Task 16: Final verification

The migration is mechanically complete after Task 15. This task runs the invariant checks from the spec and does an end-to-end visual smoke.

**Files:**
- (No file edits expected; if any visual issue surfaces, fix it inline and add a small follow-up commit.)

- [ ] **Step 1: Verify build artifacts and grep invariants**

Run from the dashboard directory:
```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor/.claude/worktrees/xenodochial-wu-9c4aba/dashboard
yarn build
```
Expected: build succeeds; `../conductor/public/dashboard/` regenerated.

```bash
grep -r "frappe-ui" src
```
Expected: no output (exit code 1).

```bash
grep -rn "<style" src | sort
```
Expected: exactly 2 lines —
```
src/components/ConfirmDialog.vue:<line>:<style scoped>
src/components/ToastHost.vue:<line>:<style scoped>
```

```bash
grep -c "frappe-ui" package.json
```
Expected: `0`.

- [ ] **Step 2: Visual smoke test (manual, in `yarn dev`)**

```bash
yarn dev
```

Walk through every route and verify:

- [ ] `/overview` — 4 NumberCards render (full width 4-col, narrow 2-col); 2 QueueCharts render with bars; loading state shown briefly
- [ ] `/feed` — Live feed renders; pause checkbox freezes the list; clicking a row navigates to `/jobs/<id>`
- [ ] `/jobs` — Master-detail layout; filter by status/method/queue; click row → detail with Overview/Runs/Args subtabs; Retry/Cancel buttons enabled for appropriate statuses; ConfirmDialog fades+pops; ToastHost slides in
- [ ] `/dlq` — Master-detail; checkbox bulk selection shows bulk-bar; Retry/Discard/Edit-and-retry actions; EditAndRetryModal opens for JSON-safe entries; safety pill shows green for safe / amber for unsafe
- [ ] `/schedules` — Schedule table; click row → detail with cron, last dispatch, next 10 fires, MiniCalendar (today outlined, fire dots on relevant days), recent runs; "Run now" with confirm dialog
- [ ] `/workers` — Sorted alive-first; click row → detail with heartbeat info, current job, recent jobs
- [ ] `/workflows` — Workflows table; click row → highlights yellow; recent runs table; click run → workflow run detail
- [ ] Workflow run detail (`/workflows/runs/<id>`) — DAG renders (Mermaid SVG), step runs table, Cancel button only for RUNNING + operator/sysmgr

- [ ] **Step 3: Browser console check**

In the browser devtools console for the running `yarn dev` page:
- No CSS-related errors
- No 404s for missing assets
- No Vue warnings about missing imports or undefined props

- [ ] **Step 4: If any visual issue surfaced in Step 2, fix and commit**

If a class string is wrong or a layout broke:
1. Identify the file and line
2. Adjust the utility classes
3. Verify the fix with `yarn build && yarn dev`
4. Commit with message `fix(dashboard): <component> <issue>`

- [ ] **Step 5: Final commit (if no fixes needed, or after fixes)**

If no edits in Step 4, no additional commit is needed — the migration is complete.

If any fixes were committed in Step 4, leave them as separate commits in the branch.

---

## Self-Review Checklist (already run)

**Spec coverage:**
- ✅ Build wiring (Section 2 of spec) → Task 1
- ✅ Theme tokens (Section 1 of spec) → Task 1, Step 2
- ✅ App.vue migration (covers shell + tabs + filter-button rule deletion) → Task 2
- ✅ All 17 .vue files migrated → Tasks 2-15
- ✅ Edge case 1 (filter-button utility string applied inline per page) → Tasks 11-14
- ✅ Edge case 2 (ConfirmDialog @keyframes preserved) → Task 6
- ✅ Edge case 3 (ToastHost transitions preserved) → Task 7
- ✅ Edge case 4 (OverviewPage @media → md: breakpoint) → Task 9
- ✅ Edge case 5 (Mermaid preflight check) → Task 4 / Task 16 visual smoke
- ✅ Edge case 6 (build output regenerated) → Task 1 / Task 16
- ✅ Edge case 7 (frappe-ui grep clean) → Task 1 / Task 16
- ✅ Acceptance criteria → Task 16

**Placeholder scan:** No "TBD", "TODO", or "implement later" lines. Every code step has full code. Every command has expected output.

**Type consistency:** No method renames. `StatusBadge` props (`status: String`) stay the same. `NumberCard` props (`value`, `label`) stay the same. Filter-button utility string is identical across Tasks 11, 12, 13, 14.

---

## Out of Scope

(Reproduced from the spec for the engineer's reference.)

This plan does **not**:
- Adopt `frappe-ui` components
- Visually redesign or restructure components
- Extract reusable Vue components for repeated table/master-detail shells
- Migrate page-by-page across multiple PRs
- Add custom design tokens beyond the two color aliases and one font-size step
- Change template logic (`v-if`, `v-for`, computed properties, event handlers)
- Touch `dashboard/src/api.js`, `realtime.js`, `router.js`, `stores/*`
