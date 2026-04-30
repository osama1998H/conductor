# shadcn-vue Dashboard Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current ad-hoc Tailwind dashboard with shadcn-vue primitives, a sidebar shell, dark/light mode, and Tanstack data tables — preserving every existing behavior.

**Architecture:** New shell renders a persistent `Sidebar` + `Header` and routes the existing 8 pages through a `<router-view>`. Each page is rebuilt with shadcn-vue components (Card, Tabs, Table, DataTable, Badge, Sheet, Sonner, AlertDialog). All data wiring (`api.js`, `realtime.js`, `useDetailSubscription`, `useAutoPolling`, `useUserRoles`) is preserved verbatim. Two stores (`useToast`, `useConfirm`) retarget internally; their public APIs are unchanged so call sites in pages compile without edit.

**Tech Stack:** Vue 3 (Composition API, JS only), Vue Router 4, Tailwind v4, shadcn-vue (copy-paste components), reka-ui, lucide-vue-next, @tanstack/vue-table, vue-sonner, @vueuse/core.

**Branch:** `feat/dashboard-shadcn-vue` (already cut from `develop`, spec already committed).

**Spec:** `docs/superpowers/specs/2026-04-30-shadcn-vue-dashboard-design.md`.

**Testing model:** UI automated tests are out of scope per the spec. Each task ends with a build-and-eyeball verification step (`yarn build` for compile, then visit the page in a browser via the existing dev server). The Python suite is unaffected — do not run pytest as part of this work.

---

## File structure

| File | Status | Responsibility |
|---|---|---|
| `dashboard/package.json` | Modify | Add deps |
| `dashboard/components.json` | Create | shadcn-vue config (`tsx: false`) |
| `dashboard/src/lib/utils.js` | Create | `cn()` helper |
| `dashboard/src/app.css` | Modify | shadcn theme CSS variables (light + dark) |
| `dashboard/src/components/ui/**` | Create | ~25 shadcn-vue copied components |
| `dashboard/src/stores/useColorMode.js` | Create | light/dark/system mode |
| `dashboard/src/stores/useToast.js` | Modify | Retarget to `vue-sonner` |
| `dashboard/src/stores/useConfirm.js` | Modify | Retarget render to shadcn `AlertDialog` |
| `dashboard/src/components/ModeToggle.vue` | Create | Header dropdown |
| `dashboard/src/components/AppSidebar.vue` | Create | Sidebar nav |
| `dashboard/src/components/AppHeader.vue` | Create | Breadcrumb + ModeToggle |
| `dashboard/src/components/JobsDataTable.vue` | Create | Tanstack table for Jobs |
| `dashboard/src/components/DlqDataTable.vue` | Create | Tanstack table for DLQ |
| `dashboard/src/components/StatusBadge.vue` | Modify | Wrap shadcn `Badge` |
| `dashboard/src/components/NumberCard.vue` | Modify | Wrap shadcn `Card` |
| `dashboard/src/components/ConfirmDialog.vue` | Modify | Wrap shadcn `AlertDialog` |
| `dashboard/src/components/EditAndRetryModal.vue` | Modify | Wrap shadcn `Dialog` |
| `dashboard/src/components/ToastHost.vue` | Delete | Replaced by `<Toaster />` from `vue-sonner` |
| `dashboard/src/App.vue` | Modify | New shell |
| `dashboard/src/pages/OverviewPage.vue` | Modify | Card-based stat grid |
| `dashboard/src/pages/FeedPage.vue` | Modify | ScrollArea + Card rows |
| `dashboard/src/pages/JobsPage.vue` | Modify | DataTable + Tabs + Cards |
| `dashboard/src/pages/DlqPage.vue` | Modify | DataTable + bulk-action bar + Cards |
| `dashboard/src/pages/SchedulesPage.vue` | Modify | Table + Switch + Sheet detail |
| `dashboard/src/pages/WorkersPage.vue` | Modify | Table + Tooltip |
| `dashboard/src/pages/WorkflowsPage.vue` | Modify | Card grid + Table |
| `dashboard/src/pages/WorkflowRunDetailPage.vue` | Modify | Card-wrapped DAG + Table |

---

## Conventions for every task

- Work directory is `dashboard/`. Run all `yarn`/`npx` commands from there.
- After every task, run `yarn build` from `dashboard/` and confirm it exits 0. If it fails, do not commit — diagnose first.
- For visual smoke checks, run `yarn dev` from `dashboard/` and open the printed URL (default `http://localhost:5173`) in a browser. After verifying, kill the dev server before continuing to the next task.
- Commit after each task. Use `git add` with explicit paths, never `git add -A`.
- Do not mix unrelated changes in a single commit.

---

## Task 1: Install shadcn-vue, dependencies, and base scaffolding

**Files:**
- Modify: `dashboard/package.json`
- Create: `dashboard/components.json`
- Create: `dashboard/src/lib/utils.js`

- [ ] **Step 1: Install runtime dependencies**

From `dashboard/`:

```bash
yarn add reka-ui class-variance-authority clsx tailwind-merge lucide-vue-next \
         @tanstack/vue-table vue-sonner @vueuse/core
```

Expected: `package.json` gains the listed entries under `dependencies`. `yarn.lock` updates.

- [ ] **Step 2: Install shadcn-vue CLI as dev dependency**

```bash
yarn add -D shadcn-vue
```

- [ ] **Step 3: Create `dashboard/components.json`**

Write this file exactly:

```json
{
  "$schema": "https://shadcn-vue.com/schema.json",
  "style": "new-york",
  "typescript": false,
  "tailwind": {
    "config": "",
    "css": "src/app.css",
    "baseColor": "zinc",
    "cssVariables": true
  },
  "aliases": {
    "components": "@/components",
    "composables": "@/stores",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib"
  },
  "iconLibrary": "lucide"
}
```

- [ ] **Step 4: Create `dashboard/src/lib/utils.js`**

```javascript
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Verify install**

```bash
yarn build
```

Expected: build succeeds. No new warnings about missing modules.

- [ ] **Step 6: Commit**

```bash
git add dashboard/package.json dashboard/yarn.lock dashboard/components.json dashboard/src/lib/utils.js
git commit -m "feat(dashboard): scaffold shadcn-vue install (deps + components.json + cn helper)"
```

---

## Task 2: Apply shadcn theme variables to app.css

**Files:**
- Modify: `dashboard/src/app.css`

- [ ] **Step 1: Replace `dashboard/src/app.css` contents**

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
  --text-2xs: 11px;
  --text-2xs--line-height: 1rem;
}

:root {
  --radius: 0.5rem;
  --background: oklch(1 0 0);
  --foreground: oklch(0.141 0.005 285.823);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.141 0.005 285.823);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.141 0.005 285.823);
  --primary: oklch(0.723 0.219 149.579);
  --primary-foreground: oklch(0.982 0.018 155.826);
  --secondary: oklch(0.967 0.001 286.375);
  --secondary-foreground: oklch(0.21 0.006 285.885);
  --muted: oklch(0.967 0.001 286.375);
  --muted-foreground: oklch(0.552 0.016 285.938);
  --accent: oklch(0.967 0.001 286.375);
  --accent-foreground: oklch(0.21 0.006 285.885);
  --destructive: oklch(0.577 0.245 27.325);
  --border: oklch(0.92 0.004 286.32);
  --input: oklch(0.92 0.004 286.32);
  --ring: oklch(0.723 0.219 149.579);
  --sidebar: oklch(0.985 0 0);
  --sidebar-foreground: oklch(0.141 0.005 285.823);
  --sidebar-primary: oklch(0.723 0.219 149.579);
  --sidebar-primary-foreground: oklch(0.982 0.018 155.826);
  --sidebar-accent: oklch(0.967 0.001 286.375);
  --sidebar-accent-foreground: oklch(0.21 0.006 285.885);
  --sidebar-border: oklch(0.92 0.004 286.32);
  --sidebar-ring: oklch(0.723 0.219 149.579);
}

.dark {
  --background: oklch(0.141 0.005 285.823);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.21 0.006 285.885);
  --card-foreground: oklch(0.985 0 0);
  --popover: oklch(0.21 0.006 285.885);
  --popover-foreground: oklch(0.985 0 0);
  --primary: oklch(0.696 0.17 162.48);
  --primary-foreground: oklch(0.393 0.095 152.535);
  --secondary: oklch(0.274 0.006 286.033);
  --secondary-foreground: oklch(0.985 0 0);
  --muted: oklch(0.274 0.006 286.033);
  --muted-foreground: oklch(0.705 0.015 286.067);
  --accent: oklch(0.274 0.006 286.033);
  --accent-foreground: oklch(0.985 0 0);
  --destructive: oklch(0.704 0.191 22.216);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.527 0.154 150.069);
  --sidebar: oklch(0.21 0.006 285.885);
  --sidebar-foreground: oklch(0.985 0 0);
  --sidebar-primary: oklch(0.696 0.17 162.48);
  --sidebar-primary-foreground: oklch(0.393 0.095 152.535);
  --sidebar-accent: oklch(0.274 0.006 286.033);
  --sidebar-accent-foreground: oklch(0.985 0 0);
  --sidebar-border: oklch(1 0 0 / 10%);
  --sidebar-ring: oklch(0.527 0.154 150.069);
}

@layer base {
  * {
    border-color: var(--border);
  }
  body {
    background-color: var(--background);
    color: var(--foreground);
  }
}
```

- [ ] **Step 2: Install the animation utility plugin**

```bash
yarn add tw-animate-css
```

- [ ] **Step 3: Verify build**

```bash
yarn build
```

Expected: build succeeds. The page may look broken when opened — that is acceptable; the shell rewrite in Task 4 fixes it.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/app.css dashboard/package.json dashboard/yarn.lock
git commit -m "feat(dashboard): add shadcn-vue theme variables (zinc base, green accent, dark+light)"
```

---

## Task 3: Color mode store and ModeToggle

**Files:**
- Create: `dashboard/src/stores/useColorMode.js`
- Create: `dashboard/src/components/ModeToggle.vue`

- [ ] **Step 1: Add the dropdown-menu and button shadcn components**

```bash
npx shadcn-vue@latest add button dropdown-menu --yes
```

Expected: creates `src/components/ui/button/` and `src/components/ui/dropdown-menu/` with `index.js` barrel files and `.vue` components.

- [ ] **Step 2: Create `dashboard/src/stores/useColorMode.js`**

```javascript
import { useColorMode as vueUseColorMode } from "@vueuse/core";

export function useColorMode() {
  return vueUseColorMode({
    selector: "html",
    attribute: "class",
    modes: { light: "light", dark: "dark" },
    storageKey: "conductor-color-mode",
    initialValue: "system",
  });
}
```

- [ ] **Step 3: Create `dashboard/src/components/ModeToggle.vue`**

```vue
<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button variant="outline" size="icon" aria-label="Toggle theme">
        <Sun class="h-4 w-4 scale-100 rotate-0 transition-all dark:scale-0 dark:-rotate-90" />
        <Moon class="absolute h-4 w-4 scale-0 rotate-90 transition-all dark:scale-100 dark:rotate-0" />
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      <DropdownMenuItem @click="mode = 'light'">Light</DropdownMenuItem>
      <DropdownMenuItem @click="mode = 'dark'">Dark</DropdownMenuItem>
      <DropdownMenuItem @click="mode = 'system'">System</DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>

<script setup>
import { Sun, Moon } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useColorMode } from "@/stores/useColorMode";

const mode = useColorMode();
</script>
```

- [ ] **Step 4: Verify build**

```bash
yarn build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/stores/useColorMode.js dashboard/src/components/ModeToggle.vue dashboard/src/components/ui/ dashboard/components.json
git commit -m "feat(dashboard): add light/dark/system color mode + ModeToggle"
```

---

## Task 4: Toast retarget — vue-sonner replaces ToastHost

**Files:**
- Modify: `dashboard/src/stores/useToast.js`
- Delete: `dashboard/src/components/ToastHost.vue`
- (App.vue is updated in Task 6 along with shell)

- [ ] **Step 1: Install the sonner shadcn wrapper**

```bash
npx shadcn-vue@latest add sonner --yes
```

Expected: creates `src/components/ui/sonner/Sonner.vue` (a thin wrapper around `vue-sonner`'s `Toaster`).

- [ ] **Step 2: Replace `dashboard/src/stores/useToast.js`**

```javascript
import { toast as sonner } from "vue-sonner";

const TYPE_TO_FN = {
  success: sonner.success,
  error: sonner.error,
  warning: sonner.warning,
  info: sonner,
};

export function toast(message, type = "info") {
  const fn = TYPE_TO_FN[type] || sonner;
  fn(message);
}
```

The previous `useToasts()` export is no longer needed because `<Toaster />` from `vue-sonner` reads from its own internal queue.

- [ ] **Step 3: Delete `dashboard/src/components/ToastHost.vue`**

```bash
git rm dashboard/src/components/ToastHost.vue
```

- [ ] **Step 4: Verify build**

```bash
yarn build
```

Expected: build fails with "ToastHost not found" referenced from `App.vue`. That is expected — Task 6 rewrites `App.vue`. Do not commit yet; continue to Task 5 first to keep the commit history coherent.

> **Important:** the build is intentionally broken between Task 4 and Task 6. Do not commit Task 4 alone. The single commit at the end of Task 6 lands all three changes (toast retarget, confirm retarget, shell rewrite) together so the working tree compiles at every commit boundary.

---

## Task 5: Confirm dialog retarget — shadcn AlertDialog

**Files:**
- Modify: `dashboard/src/stores/useConfirm.js` (no public API change)
- Modify: `dashboard/src/components/ConfirmDialog.vue` (full rewrite to wrap `AlertDialog`)

- [ ] **Step 1: Add the alert-dialog shadcn component**

```bash
npx shadcn-vue@latest add alert-dialog --yes
```

- [ ] **Step 2: Rewrite `dashboard/src/components/ConfirmDialog.vue`**

```vue
<template>
  <AlertDialog :open="state.open" @update:open="onOpenChange">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{{ state.title }}</AlertDialogTitle>
        <AlertDialogDescription>{{ state.message }}</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="onCancel">{{ state.cancelText }}</AlertDialogCancel>
        <AlertDialogAction
          :class="state.danger ? 'bg-destructive text-white hover:bg-destructive/90' : ''"
          @click="onOk"
        >{{ state.confirmText }}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

<script setup>
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useConfirmState, _resolve } from "@/stores/useConfirm";

const state = useConfirmState();

function onOk() { _resolve(true); }
function onCancel() { _resolve(false); }

function onOpenChange(open) {
  if (!open) _resolve(false);
}
</script>
```

- [ ] **Step 3: Verify the existing `useConfirm.js` requires no edit**

Read `dashboard/src/stores/useConfirm.js` — it exports `confirm()`, `_resolve()`, and `useConfirmState()`. The new `ConfirmDialog.vue` consumes all three via the same names. **No edit to `useConfirm.js` is required.** Move on.

- [ ] **Step 4: No commit yet**

Build is still broken from Task 4. Continue to Task 6.

---

## Task 6: Shell — AppSidebar, AppHeader, App.vue rewrite

**Files:**
- Create: `dashboard/src/components/AppSidebar.vue`
- Create: `dashboard/src/components/AppHeader.vue`
- Modify: `dashboard/src/App.vue`

- [ ] **Step 1: Add the shell shadcn components**

```bash
npx shadcn-vue@latest add sidebar separator breadcrumb tooltip --yes
```

Expected: creates `src/components/ui/sidebar/`, `src/components/ui/separator/`, `src/components/ui/breadcrumb/`, `src/components/ui/tooltip/`.

- [ ] **Step 2: Create `dashboard/src/components/AppSidebar.vue`**

```vue
<template>
  <Sidebar collapsible="icon">
    <SidebarHeader>
      <div class="flex items-center gap-2 px-2 py-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold">
          C
        </div>
        <span class="font-semibold group-data-[collapsible=icon]:hidden">Conductor</span>
      </div>
    </SidebarHeader>
    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Operations</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="link in navLinks" :key="link.to">
              <SidebarMenuButton as-child :is-active="isActive(link.to)" :tooltip="link.label">
                <RouterLink :to="link.to">
                  <component :is="link.icon" />
                  <span>{{ link.label }}</span>
                </RouterLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>
  </Sidebar>
</template>

<script setup>
import { useRoute, RouterLink } from "vue-router";
import {
  LayoutDashboard, Activity, ListChecks, AlertTriangle,
  CalendarClock, Users, GitBranch,
} from "lucide-vue-next";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

const route = useRoute();

const navLinks = [
  { to: "/overview",  label: "Overview",   icon: LayoutDashboard },
  { to: "/feed",      label: "Live Feed",  icon: Activity },
  { to: "/jobs",      label: "Jobs",       icon: ListChecks },
  { to: "/dlq",       label: "DLQ",        icon: AlertTriangle },
  { to: "/schedules", label: "Schedules",  icon: CalendarClock },
  { to: "/workers",   label: "Workers",    icon: Users },
  { to: "/workflows", label: "Workflows",  icon: GitBranch },
];

function isActive(prefix) {
  return route.path === prefix || route.path.startsWith(prefix + "/");
}
</script>
```

- [ ] **Step 3: Create `dashboard/src/components/AppHeader.vue`**

```vue
<template>
  <header class="flex h-14 shrink-0 items-center gap-2 border-b px-4">
    <SidebarTrigger />
    <Separator orientation="vertical" class="mr-2 h-4" />
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbPage>{{ pageTitle }}</BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
    <div class="ml-auto">
      <ModeToggle />
    </div>
  </header>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
} from "@/components/ui/breadcrumb";
import ModeToggle from "@/components/ModeToggle.vue";

const route = useRoute();

const TITLES = {
  "/overview": "Overview",
  "/feed": "Live Feed",
  "/jobs": "Jobs",
  "/dlq": "DLQ",
  "/schedules": "Schedules",
  "/workers": "Workers",
  "/workflows": "Workflows",
};

const pageTitle = computed(() => {
  const match = Object.keys(TITLES).find(p => route.path === p || route.path.startsWith(p + "/"));
  return match ? TITLES[match] : "Conductor";
});
</script>
```

- [ ] **Step 4: Replace `dashboard/src/App.vue`**

```vue
<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset>
      <AppHeader />
      <main class="flex-1 p-4 overflow-auto">
        <RouterView />
      </main>
    </SidebarInset>
    <ConfirmDialog />
    <Toaster />
  </SidebarProvider>
</template>

<script setup>
import { RouterView } from "vue-router";
import AppSidebar from "@/components/AppSidebar.vue";
import AppHeader from "@/components/AppHeader.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
</script>
```

- [ ] **Step 5: Verify build**

```bash
yarn build
```

Expected: build succeeds. No "ToastHost not found" error.

- [ ] **Step 6: Visual smoke**

```bash
yarn dev
```

Open the printed URL. Verify:
- Sidebar renders on the left with all 7 routes and icons.
- Header renders with breadcrumb and mode toggle.
- Click each nav link — the corresponding page renders inside `<main>`. Pages will look unstyled or broken — that is acceptable; per-page conversion is in Tasks 9–18.
- Click the mode toggle — Light / Dark / System options appear. Choose Dark; the shell flips to dark background. Refresh the page; choice persists.
- Click sidebar trigger; sidebar collapses to icon-only.

Kill the dev server.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/stores/useToast.js \
        dashboard/src/components/ConfirmDialog.vue \
        dashboard/src/components/AppSidebar.vue \
        dashboard/src/components/AppHeader.vue \
        dashboard/src/App.vue \
        dashboard/src/components/ui/
git rm dashboard/src/components/ToastHost.vue
git commit -m "feat(dashboard): shell rewrite (sidebar + header) and toast/confirm retarget"
```

---

## Task 7: StatusBadge — wrap shadcn Badge

**Files:**
- Modify: `dashboard/src/components/StatusBadge.vue`

- [ ] **Step 1: Add the badge shadcn component**

```bash
npx shadcn-vue@latest add badge --yes
```

- [ ] **Step 2: Rewrite `dashboard/src/components/StatusBadge.vue`**

Replace the file:

```vue
<template>
  <Badge :class="toneClasses">{{ status }}</Badge>
</template>

<script setup>
import { computed } from "vue";
import { Badge } from "@/components/ui/badge";

const props = defineProps({ status: String });

const TONE_BY_STATUS = {
  SUCCEEDED: "green",
  RUNNING: "blue",
  ALIVE: "blue",
  QUEUED: "yellow",
  SCHEDULED_RETRY: "yellow",
  FAILED: "red",
  DLQ: "red",
  TIMED_OUT: "red",
  DISPATCH_FAILED: "red",
  STALE: "red",
  CANCELLED: "grey",
  GONE: "grey",
};

const TONE_TO_CLASSES = {
  green:  "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-300 border-transparent",
  blue:   "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-300 border-transparent",
  yellow: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300 border-transparent",
  red:    "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-300 border-transparent",
  grey:   "bg-muted text-muted-foreground border-transparent",
};

const toneClasses = computed(() => TONE_TO_CLASSES[TONE_BY_STATUS[props.status] || "grey"]);
</script>
```

- [ ] **Step 3: Verify build**

```bash
yarn build
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/StatusBadge.vue dashboard/src/components/ui/badge/
git commit -m "feat(dashboard): restyle StatusBadge to wrap shadcn Badge with semantic tones"
```

---

## Task 8: NumberCard — wrap shadcn Card

**Files:**
- Modify: `dashboard/src/components/NumberCard.vue`

- [ ] **Step 1: Add the card shadcn component**

```bash
npx shadcn-vue@latest add card --yes
```

- [ ] **Step 2: Rewrite `dashboard/src/components/NumberCard.vue`**

```vue
<template>
  <Card class="cursor-pointer transition-colors hover:border-primary" @click="$emit('click')">
    <CardHeader class="pb-2">
      <CardDescription class="text-xs uppercase tracking-wider">{{ label }}</CardDescription>
    </CardHeader>
    <CardContent>
      <div class="text-3xl font-semibold">{{ value }}</div>
    </CardContent>
  </Card>
</template>

<script setup>
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

defineProps({
  value: { type: [Number, String], default: 0 },
  label: { type: String, required: true },
});
defineEmits(["click"]);
</script>
```

- [ ] **Step 3: Verify build**

```bash
yarn build
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/NumberCard.vue dashboard/src/components/ui/card/
git commit -m "feat(dashboard): restyle NumberCard to wrap shadcn Card"
```

---

## Task 9: Overview page

**Files:**
- Modify: `dashboard/src/pages/OverviewPage.vue`

- [ ] **Step 1: Replace `dashboard/src/pages/OverviewPage.vue`**

```vue
<template>
  <div class="space-y-6">
    <div v-if="!state" class="p-6 text-center text-muted-foreground">Loading…</div>
    <div v-else class="space-y-6">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <NumberCard :value="totalDepth" label="Total queue depth" @click="go('/jobs')" />
        <NumberCard :value="aliveWorkers" label="Active workers" @click="go('/workers')" />
        <NumberCard :value="dlqPending" label="DLQ pending review" @click="go('/dlq')" />
        <NumberCard :value="schedulesEnabled" label="Schedules enabled" @click="go('/schedules')" />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Queue depth by queue</CardTitle>
          </CardHeader>
          <CardContent>
            <QueueChart :data="queueDepthData" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>DLQ status counts</CardTitle>
          </CardHeader>
          <CardContent>
            <QueueChart :data="dlqData" />
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "@/stores/useDashboardState";
import NumberCard from "@/components/NumberCard.vue";
import QueueChart from "@/components/QueueChart.vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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

> **Note:** `QueueChart` is preserved as-is. If its inline SVG colors look off in dark mode, that's acceptable for this task — a follow-up can address chart theming if requested. Do not modify `QueueChart.vue` here.

- [ ] **Step 2: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/overview`. Verify: 4 stat cards render, hover gives green border, click navigates. Two charts render below in cards. Toggle dark mode; cards adapt.

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/OverviewPage.vue
git commit -m "feat(dashboard): redesign Overview page with shadcn Card grid"
```

---

## Task 10: Live Feed page

**Files:**
- Modify: `dashboard/src/pages/FeedPage.vue`

- [ ] **Step 1: Add the scroll-area, switch, and label shadcn components**

```bash
npx shadcn-vue@latest add scroll-area switch label --yes
```

- [ ] **Step 2: Replace `dashboard/src/pages/FeedPage.vue`**

```vue
<template>
  <div class="space-y-4">
    <div class="flex items-center gap-4">
      <h2 class="text-xl font-semibold">Live Feed</h2>
      <div class="flex items-center gap-2">
        <Switch id="pause" v-model:checked="paused" />
        <Label for="pause">Pause updates</Label>
      </div>
      <span class="text-xs text-muted-foreground">
        {{ paused ? "(showing snapshot)" : `(updating; ${rows.length} jobs)` }}
      </span>
    </div>

    <Card>
      <ScrollArea class="h-[calc(100vh-220px)]">
        <div
          v-for="row in rows"
          :key="row.job_id"
          class="flex items-center gap-3 px-4 py-2 border-b cursor-pointer text-sm hover:bg-muted/50"
          @click="open(row.job_id)"
        >
          <span class="font-mono text-2xs text-muted-foreground min-w-[140px]">{{ formatTime(row.enqueued_at) }}</span>
          <StatusBadge :status="row.status" />
          <span class="text-xs text-muted-foreground min-w-20">{{ row.queue }}</span>
          <code class="font-mono text-xs flex-1 min-w-0 truncate">{{ row.method }}</code>
          <span class="font-mono text-2xs text-muted-foreground">{{ row.job_id.slice(0, 8) }}…</span>
        </div>
        <div v-if="!rows.length" class="p-6 text-center text-muted-foreground">No jobs yet.</div>
      </ScrollArea>
    </Card>
  </div>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "@/stores/useDashboardState";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

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

- [ ] **Step 3: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/feed`. Verify: list of recent jobs appears inside a card; switch toggles pause; rows are clickable.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/FeedPage.vue dashboard/src/components/ui/scroll-area/ dashboard/src/components/ui/switch/ dashboard/src/components/ui/label/
git commit -m "feat(dashboard): redesign Live Feed page with ScrollArea + Switch"
```

---

## Task 11: Workers page

**Files:**
- Modify: `dashboard/src/pages/WorkersPage.vue`

The existing page binds to props.worker_id and uses fields: `row.name`, `row.status`, `row.host`, `row.pid`, `row.queues`, `row.last_heartbeat`. Detail uses `detail.name`, `detail.host`, `detail.pid`, `detail.conductor_version`, `detail.last_heartbeat`, `detail.heartbeat_age_seconds`, `detail.started_at`, `detail.current_job`, `detail.recent_jobs[]`. Helpers `parseQueues()`, `heartbeatAge()`, computed `sortedRows`, ref `currentJobStatus`. **Preserve all of these by name.**

- [ ] **Step 1: Add the table and input shadcn components**

```bash
npx shadcn-vue@latest add table input --yes
```

- [ ] **Step 2: Replace `dashboard/src/pages/WorkersPage.vue` entirely**

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="mb-3">
        <Button variant="outline" @click="reload">Refresh</Button>
      </div>
      <Card class="p-0 flex-1 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Worker</TableHead>
              <TableHead>Host</TableHead>
              <TableHead>PID</TableHead>
              <TableHead>Queues</TableHead>
              <TableHead>HB age</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in sortedRows"
              :key="row.name"
              :class="['cursor-pointer', row.name === worker_id ? 'bg-muted' : 'hover:bg-muted/50']"
              @click="open(row.name)"
            >
              <TableCell><StatusBadge :status="row.status" /></TableCell>
              <TableCell class="font-mono text-xs">{{ row.name }}</TableCell>
              <TableCell>{{ row.host }}</TableCell>
              <TableCell>{{ row.pid }}</TableCell>
              <TableCell class="font-mono text-xs">{{ parseQueues(row.queues) }}</TableCell>
              <TableCell>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <span class="text-xs text-muted-foreground">{{ heartbeatAge(row.last_heartbeat) }}</span>
                  </TooltipTrigger>
                  <TooltipContent>{{ row.last_heartbeat || "—" }}</TooltipContent>
                </Tooltip>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No workers registered.</div>
      </Card>
    </div>

    <div v-if="worker_id" class="flex-1 min-w-0 overflow-auto">
      <Card v-if="!detail">
        <CardContent class="p-6 text-center text-muted-foreground">Loading…</CardContent>
      </Card>
      <Card v-else>
        <CardHeader class="flex flex-row items-center gap-2 flex-wrap">
          <StatusBadge :status="detail.status" />
          <code class="font-mono text-sm">{{ detail.name }}</code>
          <span class="text-xs text-muted-foreground">· {{ detail.host }}:{{ detail.pid }}</span>
          <span v-if="detail.conductor_version" class="text-xs text-muted-foreground">· v{{ detail.conductor_version }}</span>
        </CardHeader>
        <CardContent class="space-y-4">
          <section>
            <h4 class="text-sm font-medium mb-2">Queues</h4>
            <p class="font-mono text-sm">{{ parseQueues(detail.queues) }}</p>
          </section>

          <section>
            <h4 class="text-sm font-medium mb-2">Heartbeat</h4>
            <p class="text-sm">
              Last beat at <span class="text-2xs text-muted-foreground">{{ detail.last_heartbeat }}</span>
              ({{ detail.heartbeat_age_seconds }}s ago)
            </p>
            <p class="text-sm">
              Started at <span class="text-2xs text-muted-foreground">{{ detail.started_at }}</span>
            </p>
          </section>

          <section v-if="detail.current_job">
            <h4 class="text-sm font-medium mb-2">Currently executing</h4>
            <p class="text-sm">
              <RouterLink :to="`/jobs/${detail.current_job}`" class="font-mono text-primary hover:underline">
                {{ detail.current_job }}
              </RouterLink>
              <StatusBadge v-if="currentJobStatus" :status="currentJobStatus" class="ml-2" />
            </p>
          </section>

          <section>
            <h4 class="text-sm font-medium mb-2">Recent jobs handled</h4>
            <Table v-if="detail.recent_jobs?.length">
              <TableHeader>
                <TableRow>
                  <TableHead>Job ID</TableHead>
                  <TableHead>Method</TableHead>
                  <TableHead>Queue</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Finished</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="r in detail.recent_jobs" :key="r.job_id">
                  <TableCell>
                    <RouterLink :to="`/jobs/${r.job_id}`" class="font-mono text-primary hover:underline">
                      {{ r.job_id.slice(0, 8) }}…
                    </RouterLink>
                  </TableCell>
                  <TableCell class="font-mono text-xs">{{ r.method }}</TableCell>
                  <TableCell>{{ r.queue }}</TableCell>
                  <TableCell><StatusBadge :status="r.status" /></TableCell>
                  <TableCell class="text-2xs text-muted-foreground">{{ r.finished_at }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <div v-else class="text-muted-foreground text-sm">No recent jobs.</div>
          </section>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, toRefs } from "vue";
import { useRouter, RouterLink } from "vue-router";
import { api, getList } from "@/api";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const props = defineProps({ worker_id: String });
const router = useRouter();
const { worker_id } = toRefs(props);

const rows = ref([]);
const detail = ref(null);
const currentJobStatus = ref("");

function parseQueues(raw) {
  try {
    return (JSON.parse(raw || "[]")).join(", ");
  } catch {
    return String(raw || "");
  }
}

function heartbeatAge(hb) {
  if (!hb) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(hb).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

const STATUS_RANK = { ALIVE: 0, STALE: 1, GONE: 2 };

const sortedRows = computed(() => {
  return [...rows.value].sort((a, b) => {
    const aRank = STATUS_RANK[a.status] ?? 99;
    const bRank = STATUS_RANK[b.status] ?? 99;
    if (aRank !== bRank) return aRank - bRank;
    return new Date(b.last_heartbeat || 0) - new Date(a.last_heartbeat || 0);
  });
});

async function reload() {
  rows.value = await getList("Conductor Worker", {
    fields: ["name", "host", "pid", "queues", "status", "last_heartbeat", "started_at"],
    order_by: "last_heartbeat desc",
    limit: 100,
  });
}

reload();

function open(id) {
  router.push({ path: `/workers/${id}` });
}

async function loadDetail(id) {
  if (!id) {
    detail.value = null;
    return;
  }
  detail.value = await api.getWorker(id);
  if (detail.value?.current_job) {
    try {
      const j = await api.getJob(detail.value.current_job);
      currentJobStatus.value = j.status;
    } catch {
      currentJobStatus.value = "";
    }
  } else {
    currentJobStatus.value = "";
  }
}

watch(worker_id, loadDetail, { immediate: true });
</script>
```

- [ ] **Step 3: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/workers`. Verify the table renders sorted with ALIVE first, click selects a worker, detail card renders with Queues / Heartbeat / Currently executing / Recent jobs sections, hover-tooltip shows the exact heartbeat ISO time.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/WorkersPage.vue dashboard/src/components/ui/table/ dashboard/src/components/ui/input/
git commit -m "feat(dashboard): redesign Workers page with shadcn Table + Tooltip"
```

---

## Task 12: Workflows page

**Files:**
- Modify: `dashboard/src/pages/WorkflowsPage.vue`

The existing page binds to `workflows[]` with fields `w.workflow_name`, `w.version`, `w.active_runs`, `w.recent_runs_24h`, `w.last_version_bumped_at`, and `recentRuns[]` with `r.name`, `r.workflow`, `r.definition_version`, `r.status`, `r.started_at`, `r.finished_at`. Functions: `selectWorkflow(name)`, `refresh()`. State: `selectedWorkflow` (string).

- [ ] **Step 1: Replace `dashboard/src/pages/WorkflowsPage.vue` entirely**

```vue
<template>
  <div class="space-y-6">
    <section class="space-y-3">
      <h2 class="text-xl font-semibold">Workflow definitions</h2>
      <Card class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>Active</TableHead>
              <TableHead>24h</TableHead>
              <TableHead>Last bump</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="w in workflows"
              :key="w.workflow_name"
              :class="['cursor-pointer', selectedWorkflow === w.workflow_name ? 'bg-muted' : 'hover:bg-muted/50']"
              @click="selectWorkflow(w.workflow_name)"
            >
              <TableCell class="font-mono text-xs">{{ w.workflow_name }}</TableCell>
              <TableCell>v{{ w.version }}</TableCell>
              <TableCell>{{ w.active_runs }}</TableCell>
              <TableCell>{{ w.recent_runs_24h }}</TableCell>
              <TableCell class="text-2xs text-muted-foreground">{{ w.last_version_bumped_at || "—" }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!workflows.length" class="p-6 text-center text-muted-foreground text-sm">
          No workflows registered.
        </div>
      </Card>
    </section>

    <section class="space-y-3">
      <h3 class="text-lg font-semibold">
        {{ selectedWorkflow ? `Runs of ${selectedWorkflow}` : "Recent runs (all workflows)" }}
      </h3>
      <Card class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run ID</TableHead>
              <TableHead>Workflow</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Finished</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="r in recentRuns" :key="r.name" class="hover:bg-muted/50">
              <TableCell>
                <RouterLink :to="`/workflows/runs/${r.name}`" class="font-mono text-primary hover:underline">
                  {{ r.name }}
                </RouterLink>
              </TableCell>
              <TableCell class="font-mono text-xs">{{ r.workflow }} (v{{ r.definition_version }})</TableCell>
              <TableCell><StatusBadge :status="r.status" /></TableCell>
              <TableCell class="text-2xs text-muted-foreground">{{ r.started_at || "—" }}</TableCell>
              <TableCell class="text-2xs text-muted-foreground">{{ r.finished_at || "—" }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!recentRuns.length" class="p-6 text-center text-muted-foreground text-sm">No runs yet.</div>
      </Card>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { listWorkflows, listWorkflowRuns } from "@/api";
import { useAutoPolling } from "@/stores/useDashboardState";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

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
```

- [ ] **Step 2: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/workflows`. Verify the definitions table renders, clicking a row highlights it and reloads `recentRuns` filtered to that workflow. The recent-runs heading swaps between "Recent runs (all workflows)" and "Runs of <name>".

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/WorkflowsPage.vue
git commit -m "feat(dashboard): redesign Workflows page with shadcn Table"
```

---

## Task 13: WorkflowRunDetail page

**Files:**
- Modify: `dashboard/src/pages/WorkflowRunDetailPage.vue`

The existing page subscribes to `data` (a ref whose value has `.run`, `.snapshot`, `.steps`). The run object has `name`, `workflow`, `definition_version`, `status`, `last_error`. The steps array uses `s.step_id`, `s.is_compensation`, `s.status`, `s.started_at`, `s.finished_at`, `s.job`. The MermaidDag component takes `:snapshot` and `:steps` (NOT `:definition`/`:step_runs`). The cancel function is `cancel()` and the gate is `canCancel`.

- [ ] **Step 1: Replace `dashboard/src/pages/WorkflowRunDetailPage.vue` entirely**

```vue
<template>
  <div v-if="data && data.run" class="space-y-4">
    <Card>
      <CardHeader class="flex flex-row items-center gap-3 flex-wrap">
        <Button variant="outline" size="sm" @click="router.back()">&laquo; Back</Button>
        <CardTitle class="font-mono text-sm">{{ data.run.name }}</CardTitle>
        <StatusBadge :status="data.run.status" />
        <Button v-if="canCancel" variant="destructive" size="sm" @click="cancel">Cancel run</Button>
      </CardHeader>
      <CardContent class="text-sm space-y-1">
        <div>
          <span class="text-muted-foreground">Workflow:</span>
          <code class="font-mono ml-1">{{ data.run.workflow }}</code>
          <span class="text-muted-foreground ml-1">(v{{ data.run.definition_version }})</span>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>DAG</CardTitle></CardHeader>
      <CardContent>
        <MermaidDag :snapshot="data.snapshot" :steps="data.steps" />
      </CardContent>
    </Card>

    <Card class="p-0">
      <CardHeader><CardTitle>Step runs</CardTitle></CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Step</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Started</TableHead>
            <TableHead>Finished</TableHead>
            <TableHead>Job</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="s in data.steps" :key="s.name">
            <TableCell class="font-mono text-xs">{{ s.step_id }}</TableCell>
            <TableCell>{{ s.is_compensation ? "compensation" : "forward" }}</TableCell>
            <TableCell><StatusBadge :status="s.status" /></TableCell>
            <TableCell class="text-2xs text-muted-foreground">{{ s.started_at || "—" }}</TableCell>
            <TableCell class="text-2xs text-muted-foreground">{{ s.finished_at || "—" }}</TableCell>
            <TableCell>
              <RouterLink v-if="s.job" :to="`/jobs/${s.job}`" class="font-mono text-primary hover:underline">
                {{ s.job }}
              </RouterLink>
              <span v-else class="text-muted-foreground">—</span>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Card>

    <Card v-if="data.run.last_error">
      <CardHeader><CardTitle>Last error</CardTitle></CardHeader>
      <CardContent>
        <pre class="bg-muted p-3 rounded font-mono text-2xs overflow-x-auto">{{ data.run.last_error }}</pre>
      </CardContent>
    </Card>
  </div>
  <div v-else class="p-6 text-center text-muted-foreground">Loading…</div>
</template>

<script setup>
import { useRouter, RouterLink } from "vue-router";
import { useUserRoles } from "@/stores/useUserRoles";
import { computed, toRefs } from "vue";
import { getWorkflowRun, cancelWorkflowRun } from "@/api";
import { useDetailSubscription } from "@/stores/useDetailSubscription";
import MermaidDag from "@/components/MermaidDag.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const props = defineProps({ run_id: String });
const router = useRouter();
const { run_id } = toRefs(props);

const { data, refetch: refetchData } = useDetailSubscription(
  "Conductor Workflow Run",
  "conductor:workflow_run",
  run_id,
  () => getWorkflowRun(run_id.value),
);

const { isOperator, isSysMgr } = useUserRoles();
const canCancel = computed(() =>
  data.value && data.value.run && data.value.run.status === "RUNNING" && (isOperator.value || isSysMgr.value)
);

async function cancel() {
  await cancelWorkflowRun(run_id.value);
  await refetchData();
}
</script>
```

- [ ] **Step 2: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/workflows`, click any run name to navigate to the detail page. Verify:
- Header card shows back button, run name (monospaced), status badge, Cancel button when run is RUNNING
- DAG renders inside its own card via Mermaid
- Step runs table renders with all columns
- Last error card appears only when `data.run.last_error` is set

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/WorkflowRunDetailPage.vue
git commit -m "feat(dashboard): redesign WorkflowRunDetail with Card-wrapped DAG + Table"
```

---

## Task 14: Schedules page (Sheet for detail)

**Files:**
- Modify: `dashboard/src/pages/SchedulesPage.vue`

- [ ] **Step 1: Add the sheet shadcn component**

```bash
npx shadcn-vue@latest add sheet --yes
```

- [ ] **Step 2: Replace the `<template>` block of `dashboard/src/pages/SchedulesPage.vue`**

```vue
<template>
  <div class="space-y-4">
    <div class="flex gap-2">
      <Input v-model="filters.q" placeholder="search name…" class="max-w-xs" />
      <Button variant="outline" @click="reload">Refresh</Button>
    </div>

    <Card class="p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Cron</TableHead>
            <TableHead>TZ</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead>Next run</TableHead>
            <TableHead>Last status</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in rows"
            :key="row.name"
            :class="['cursor-pointer', row.name === name ? 'bg-muted' : 'hover:bg-muted/50']"
          >
            <TableCell class="font-mono text-xs" @click="open(row.name)">{{ row.name }}</TableCell>
            <TableCell class="font-mono text-xs" @click="open(row.name)">{{ row.cron_expression }}</TableCell>
            <TableCell @click="open(row.name)">{{ row.timezone }}</TableCell>
            <TableCell>
              <Switch
                :checked="!!row.enabled"
                :disabled="!isSysMgr"
                @update:checked="onToggleEnabled(row)"
              />
            </TableCell>
            <TableCell class="text-2xs text-muted-foreground" @click="open(row.name)">{{ row.next_run_at }}</TableCell>
            <TableCell @click="open(row.name)">
              <StatusBadge v-if="row.last_status" :status="row.last_status" />
            </TableCell>
            <TableCell>
              <Button
                size="sm"
                :disabled="!isOperator"
                @click.stop="onRunNow(row.name)"
                title="Dispatches now; cron cadence is unaffected."
              >Run now</Button>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No schedules.</div>
    </Card>

    <Sheet :open="!!name" @update:open="onSheetOpenChange">
      <SheetContent side="right" class="w-[480px] sm:w-[640px] sm:max-w-[640px] overflow-y-auto">
        <template v-if="schedule">
          <SheetHeader>
            <SheetTitle class="font-mono text-base">{{ schedule.name }}</SheetTitle>
            <SheetDescription>
              <code class="font-mono">{{ schedule.cron_expression }}</code> · {{ schedule.timezone }}
            </SheetDescription>
          </SheetHeader>

          <div class="space-y-4 py-4">
            <section>
              <h4 class="text-sm font-medium mb-2">Last dispatch</h4>
              <p v-if="schedule.last_status" class="text-sm">
                <StatusBadge :status="schedule.last_status" /> at
                <span class="text-2xs text-muted-foreground">{{ schedule.last_run_at }}</span>
              </p>
              <p v-else class="text-sm text-muted-foreground">(never dispatched)</p>
            </section>

            <section v-if="schedule.last_job">
              <h4 class="text-sm font-medium mb-2">Last job</h4>
              <p class="text-sm">
                <RouterLink :to="`/jobs/${schedule.last_job}`" class="text-primary hover:underline">
                  {{ schedule.last_job }}
                </RouterLink>
                <StatusBadge v-if="lastJobStatus" :status="lastJobStatus" class="ml-2" />
              </p>
            </section>

            <section>
              <h4 class="text-sm font-medium mb-2">Next 10 fires</h4>
              <ul class="text-2xs text-muted-foreground space-y-0.5">
                <li v-for="f in nextFires" :key="f">{{ f }}</li>
              </ul>
            </section>

            <section>
              <h4 class="text-sm font-medium mb-2">Calendar</h4>
              <MiniCalendar :fires="nextFires" />
            </section>

            <section>
              <h4 class="text-sm font-medium mb-2">Recent runs</h4>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Job ID</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Enqueued</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="r in recentRuns" :key="r.job_id">
                    <TableCell>
                      <RouterLink :to="`/jobs/${r.job_id}`" class="font-mono text-primary hover:underline">
                        {{ r.job_id.slice(0, 8) }}…
                      </RouterLink>
                    </TableCell>
                    <TableCell><StatusBadge :status="r.status" /></TableCell>
                    <TableCell class="text-2xs text-muted-foreground">{{ r.enqueued_at }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </section>
          </div>
        </template>
        <div v-else class="p-6 text-center text-muted-foreground text-sm">Loading…</div>
      </SheetContent>
    </Sheet>
  </div>
</template>
```

- [ ] **Step 3: Update `<script setup>`**

In the existing script-setup block:

1. Add imports:
   ```javascript
   import { RouterLink, useRouter } from "vue-router";
   import { Card } from "@/components/ui/card";
   import { Input } from "@/components/ui/input";
   import { Button } from "@/components/ui/button";
   import { Switch } from "@/components/ui/switch";
   import {
     Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
   } from "@/components/ui/table";
   import {
     Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
   } from "@/components/ui/sheet";
   ```
   (`useRouter` is already imported in the existing file — don't duplicate.)

2. Add a sheet open-change handler:
   ```javascript
   function onSheetOpenChange(open) {
     if (!open) router.push({ path: "/schedules" });
   }
   ```

- [ ] **Step 4: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/schedules`. Verify: table renders with switches per row; clicking a name opens a right-side sheet with detail; closing the sheet (Esc, X, or overlay click) navigates back to `/schedules`. Run-now button works; switch toggles enabled.

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/pages/SchedulesPage.vue dashboard/src/components/ui/sheet/
git commit -m "feat(dashboard): redesign Schedules with Table + Switch + right-side Sheet"
```

---

## Task 15: JobsDataTable component (Tanstack)

**Files:**
- Create: `dashboard/src/components/JobsDataTable.vue`

This component delivers the spec's promised sortable columns + pagination + faceted status filter using `@tanstack/vue-table`. The page passes in `rows` (server-fetched) and a writable `filters` object; the component drives client-side sort and pagination, and emits `filters-change` whenever the user edits the faceted filter or text inputs so the page can refetch from Frappe.

- [ ] **Step 1: Add the select shadcn component**

```bash
npx shadcn-vue@latest add select --yes
```

- [ ] **Step 2: Create `dashboard/src/components/JobsDataTable.vue`**

```vue
<template>
  <div class="space-y-3">
    <div class="flex gap-2">
      <Select :model-value="filters.status" @update:model-value="(v) => emitFilter('status', v ?? '')">
        <SelectTrigger class="w-[180px]"><SelectValue placeholder="All statuses" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="">All statuses</SelectItem>
          <SelectItem v-for="s in STATUSES" :key="s" :value="s">{{ s }}</SelectItem>
        </SelectContent>
      </Select>
      <Input
        :model-value="filters.method"
        placeholder="method contains…"
        class="max-w-xs"
        @update:model-value="(v) => emitFilter('method', v)"
      />
      <Input
        :model-value="filters.queue"
        placeholder="queue"
        class="max-w-[160px]"
        @update:model-value="(v) => emitFilter('queue', v)"
      />
      <Button variant="outline" @click="$emit('refresh')">Refresh</Button>
    </div>

    <Card class="p-0">
      <Table>
        <TableHeader>
          <TableRow v-for="headerGroup in table.getHeaderGroups()" :key="headerGroup.id">
            <TableHead
              v-for="header in headerGroup.headers"
              :key="header.id"
              :class="header.column.getCanSort() ? 'cursor-pointer select-none' : ''"
              @click="header.column.getToggleSortingHandler()?.($event)"
            >
              <FlexRender :render="header.column.columnDef.header" :props="header.getContext()" />
              <span v-if="header.column.getIsSorted() === 'asc'" class="ml-1">↑</span>
              <span v-else-if="header.column.getIsSorted() === 'desc'" class="ml-1">↓</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in table.getRowModel().rows"
            :key="row.id"
            :class="['cursor-pointer', row.original.job_id === selectedId ? 'bg-muted' : 'hover:bg-muted/50']"
            @click="$emit('select', row.original.job_id)"
          >
            <TableCell v-for="cell in row.getVisibleCells()" :key="cell.id">
              <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No jobs match.</div>
      <div v-else class="flex items-center justify-end gap-2 p-3 border-t">
        <span class="text-xs text-muted-foreground">
          Page {{ table.getState().pagination.pageIndex + 1 }} of {{ table.getPageCount() || 1 }}
          · {{ table.getRowModel().rows.length }} of {{ rows.length }} rows
        </span>
        <Button size="sm" variant="outline" :disabled="!table.getCanPreviousPage()" @click="table.previousPage()">
          Previous
        </Button>
        <Button size="sm" variant="outline" :disabled="!table.getCanNextPage()" @click="table.nextPage()">
          Next
        </Button>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { ref, h } from "vue";
import {
  FlexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useVueTable,
} from "@tanstack/vue-table";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const props = defineProps({
  rows: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  selectedId: { type: String, default: "" },
});
const emit = defineEmits(["select", "refresh", "filters-change"]);

const STATUSES = [
  "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DLQ",
  "TIMED_OUT", "SCHEDULED_RETRY", "CANCELLED", "DISPATCH_FAILED",
];

function emitFilter(key, value) {
  emit("filters-change", { ...props.filters, [key]: value });
}

const sorting = ref([{ id: "enqueued_at", desc: true }]);

const columns = [
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => h(StatusBadge, { status: row.getValue("status") }),
  },
  {
    accessorKey: "method",
    header: "Method",
    cell: ({ row }) => h("span", { class: "font-mono text-xs" }, row.getValue("method")),
  },
  { accessorKey: "queue", header: "Queue" },
  { accessorKey: "attempt", header: "Attempt" },
  {
    accessorKey: "enqueued_at",
    header: "Enqueued",
    cell: ({ row }) =>
      h("span", { class: "text-2xs text-muted-foreground" }, row.getValue("enqueued_at")),
  },
];

const table = useVueTable({
  get data() { return props.rows; },
  columns,
  state: {
    get sorting() { return sorting.value; },
  },
  onSortingChange: (updater) => {
    sorting.value = typeof updater === "function" ? updater(sorting.value) : updater;
  },
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
  getPaginationRowModel: getPaginationRowModel(),
  initialState: { pagination: { pageSize: 25 } },
});
</script>
```

- [ ] **Step 3: Verify build**

```bash
yarn build
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/JobsDataTable.vue dashboard/src/components/ui/select/
git commit -m "feat(dashboard): add JobsDataTable with Tanstack sort + pagination + faceted filter"
```

---

## Task 16: Jobs page

**Files:**
- Modify: `dashboard/src/pages/JobsPage.vue`

- [ ] **Step 1: Add the tabs shadcn component**

```bash
npx shadcn-vue@latest add tabs --yes
```

- [ ] **Step 2: Replace `dashboard/src/pages/JobsPage.vue`**

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <JobsDataTable
        :rows="rows"
        :filters="filters"
        :selected-id="job_id || ''"
        @select="open"
        @refresh="reload"
        @filters-change="onFiltersChange"
      />
    </div>

    <div v-if="job_id" class="flex-1 min-w-0 overflow-auto">
      <Card v-if="!detail">
        <CardContent class="p-6 text-center text-muted-foreground">Loading…</CardContent>
      </Card>
      <Card v-else>
        <CardHeader class="flex flex-row items-center gap-2 flex-wrap">
          <StatusBadge :status="detail.status" />
          <code class="font-mono text-sm">{{ detail.method }}</code>
          <span class="text-xs text-muted-foreground">· attempt {{ detail.attempt }}/{{ detail.max_attempts }}</span>
          <span class="text-xs text-muted-foreground">· queue {{ detail.queue }}</span>
        </CardHeader>
        <CardContent>
          <Tabs v-model="subtab" default-value="overview">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="runs">Runs ({{ detail.runs?.length || 0 }})</TabsTrigger>
              <TabsTrigger value="args">Args</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" class="space-y-4">
              <p v-if="detail.last_error_message" class="text-destructive text-sm">
                {{ detail.last_error_type }}: {{ detail.last_error_message }}
              </p>
              <details v-if="detail.last_traceback">
                <summary class="cursor-pointer text-sm">Traceback</summary>
                <pre class="font-mono text-2xs bg-muted p-2 rounded max-h-96 overflow-auto mt-2">{{ detail.last_traceback }}</pre>
              </details>
              <div class="flex gap-2">
                <Button :disabled="!canRetry" @click="onRetry">Retry</Button>
                <Button variant="destructive" :disabled="!canCancel" @click="onCancel">Cancel</Button>
              </div>
            </TabsContent>

            <TabsContent value="runs">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Finished</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="r in (detail.runs || [])" :key="r.attempt_number">
                    <TableCell>{{ r.attempt_number }}</TableCell>
                    <TableCell><StatusBadge :status="r.status" /></TableCell>
                    <TableCell class="text-2xs text-muted-foreground">{{ r.started_at }}</TableCell>
                    <TableCell class="text-2xs text-muted-foreground">{{ r.finished_at }}</TableCell>
                    <TableCell>{{ r.duration_ms }}ms</TableCell>
                    <TableCell class="font-mono text-xs">{{ r.error_type }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TabsContent>

            <TabsContent value="args" class="space-y-3">
              <h4 class="text-sm font-medium">args</h4>
              <JsonViewer :value="detail.args_decoded" />
              <h4 class="text-sm font-medium">kwargs</h4>
              <JsonViewer :value="detail.kwargs_decoded" />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList } from "@/api";
import { useDetailSubscription } from "@/stores/useDetailSubscription";
import { useUserRoles } from "@/stores/useUserRoles";
import { confirm } from "@/stores/useConfirm";
import { toast } from "@/stores/useToast";
import StatusBadge from "@/components/StatusBadge.vue";
import JsonViewer from "@/components/JsonViewer.vue";
import JobsDataTable from "@/components/JobsDataTable.vue";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const props = defineProps({ job_id: String });
const router = useRouter();
const { job_id } = toRefs(props);

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

function onFiltersChange(next) {
  Object.assign(filters, next);
}

function open(id) { router.push({ path: `/jobs/${id}` }); }

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

- [ ] **Step 3: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/jobs`. Verify: filter row works, list renders, clicking a row shows the detail card with three tabs (Overview / Runs / Args). Tabs swap content. Retry / Cancel buttons enable/disable correctly. Confirm dialog appears via shadcn AlertDialog.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/pages/JobsPage.vue dashboard/src/components/ui/tabs/
git commit -m "feat(dashboard): redesign Jobs page (DataTable + Tabs + Card detail)"
```

---

## Task 17: DLQ page + EditAndRetryModal restyle

**Files:**
- Modify: `dashboard/src/pages/DlqPage.vue`
- Modify: `dashboard/src/components/EditAndRetryModal.vue`
- Create: `dashboard/src/components/DlqDataTable.vue`

- [ ] **Step 1: Add the dialog, checkbox, and textarea shadcn components**

```bash
npx shadcn-vue@latest add dialog checkbox textarea --yes
```

- [ ] **Step 2: Replace `dashboard/src/components/EditAndRetryModal.vue` entirely**

The existing component validates args + kwargs into a single `error` ref (not two), and disables the save button only on `saving`. Preserving that exactly:

```vue
<template>
  <Dialog :open="true" @update:open="(o) => !o && $emit('cancel')">
    <DialogContent class="sm:max-w-[640px] max-h-[80vh] overflow-auto">
      <DialogHeader>
        <DialogTitle>Edit &amp; retry — {{ entryName }}</DialogTitle>
        <DialogDescription class="text-xs">
          JSON-validated on save. Edited payload must remain JSON-native.
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-3">
        <div>
          <Label>args (JSON array)</Label>
          <Textarea v-model="argsText" rows="5" class="font-mono text-xs" />
        </div>
        <div>
          <Label>kwargs (JSON object)</Label>
          <Textarea v-model="kwargsText" rows="10" class="font-mono text-xs" />
        </div>
        <p v-if="error" class="text-destructive text-sm">{{ error }}</p>
      </div>

      <DialogFooter>
        <Button variant="outline" :disabled="saving" @click="$emit('cancel')">Cancel</Button>
        <Button :disabled="saving" @click="onSave">{{ saving ? "Saving…" : "Save & retry" }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref } from "vue";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

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
    const newId = await api.dlqEditAndRetry(
      props.entryName,
      JSON.stringify(parsedArgs),
      JSON.stringify(parsedKwargs),
    );
    emit("saved", newId);
  } catch (e) {
    error.value = e.message || "Save failed";
  } finally {
    saving.value = false;
  }
}
</script>
```

- [ ] **Step 3: Create `dashboard/src/components/DlqDataTable.vue` (Tanstack-driven)**

Same Tanstack pattern as JobsDataTable — sortable columns, pagination, faceted status filter — plus a per-row checkbox column.

```vue
<template>
  <div class="space-y-3">
    <div class="flex gap-2">
      <Select :model-value="filters.status" @update:model-value="(v) => emitFilter('status', v ?? '')">
        <SelectTrigger class="w-[200px]"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value="">All statuses</SelectItem>
          <SelectItem value="PENDING_REVIEW">Pending review</SelectItem>
          <SelectItem value="RETRIED">Retried</SelectItem>
          <SelectItem value="DISCARDED">Discarded</SelectItem>
        </SelectContent>
      </Select>
      <Input
        :model-value="filters.queue"
        placeholder="queue"
        class="max-w-[160px]"
        @update:model-value="(v) => emitFilter('queue', v)"
      />
      <Button variant="outline" @click="$emit('refresh')">Refresh</Button>
    </div>

    <Card class="p-0">
      <Table>
        <TableHeader>
          <TableRow v-for="headerGroup in table.getHeaderGroups()" :key="headerGroup.id">
            <TableHead
              v-for="header in headerGroup.headers"
              :key="header.id"
              :class="header.column.getCanSort() ? 'cursor-pointer select-none' : ''"
              @click="header.column.getToggleSortingHandler()?.($event)"
            >
              <FlexRender :render="header.column.columnDef.header" :props="header.getContext()" />
              <span v-if="header.column.getIsSorted() === 'asc'" class="ml-1">↑</span>
              <span v-else-if="header.column.getIsSorted() === 'desc'" class="ml-1">↓</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in table.getRowModel().rows"
            :key="row.id"
            :class="['cursor-pointer', row.original.name === selectedId ? 'bg-muted' : 'hover:bg-muted/50']"
          >
            <TableCell @click.stop>
              <Checkbox
                :checked="selected.has(row.original.name)"
                @update:checked="$emit('toggle-select', row.original.name)"
              />
            </TableCell>
            <TableCell
              v-for="cell in row.getVisibleCells().slice(1)"
              :key="cell.id"
              @click="$emit('select', row.original.name)"
            >
              <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No DLQ entries match.</div>
      <div v-else class="flex items-center justify-end gap-2 p-3 border-t">
        <span class="text-xs text-muted-foreground">
          Page {{ table.getState().pagination.pageIndex + 1 }} of {{ table.getPageCount() || 1 }}
          · {{ table.getRowModel().rows.length }} of {{ rows.length }} rows
        </span>
        <Button size="sm" variant="outline" :disabled="!table.getCanPreviousPage()" @click="table.previousPage()">
          Previous
        </Button>
        <Button size="sm" variant="outline" :disabled="!table.getCanNextPage()" @click="table.nextPage()">
          Next
        </Button>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { ref, h } from "vue";
import {
  FlexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useVueTable,
} from "@tanstack/vue-table";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const props = defineProps({
  rows: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  selected: { type: Set, required: true },
  selectedId: { type: String, default: "" },
});
const emit = defineEmits(["select", "toggle-select", "refresh", "filters-change"]);

function emitFilter(key, value) {
  emit("filters-change", { ...props.filters, [key]: value });
}

const sorting = ref([{ id: "moved_at", desc: true }]);

const columns = [
  // First column is the checkbox; its cell renders nothing — the row template handles the checkbox.
  {
    id: "select",
    header: () => h("span", { class: "sr-only" }, "Select"),
    cell: () => null,
    enableSorting: false,
  },
  { accessorKey: "queue", header: "Queue" },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => h(StatusBadge, { status: row.getValue("status") }),
  },
  { accessorKey: "attempts", header: "Attempts" },
  {
    accessorKey: "last_error_type",
    header: "Last error",
    cell: ({ row }) => h("span", { class: "font-mono text-xs" }, row.getValue("last_error_type")),
  },
  {
    accessorKey: "moved_at",
    header: "Moved at",
    cell: ({ row }) =>
      h("span", { class: "text-2xs text-muted-foreground" }, row.getValue("moved_at")),
  },
];

const table = useVueTable({
  get data() { return props.rows; },
  columns,
  state: {
    get sorting() { return sorting.value; },
  },
  onSortingChange: (updater) => {
    sorting.value = typeof updater === "function" ? updater(sorting.value) : updater;
  },
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
  getPaginationRowModel: getPaginationRowModel(),
  initialState: { pagination: { pageSize: 25 } },
});
</script>
```

- [ ] **Step 4: Replace `dashboard/src/pages/DlqPage.vue`**

```vue
<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col gap-3">
      <DlqDataTable
        :rows="rows"
        :filters="filters"
        :selected="selected"
        :selected-id="entry_name || ''"
        @select="open"
        @toggle-select="toggleSelect"
        @refresh="reload"
        @filters-change="onFiltersChange"
      />

      <Card v-if="selected.size > 0" class="p-3">
        <div class="flex gap-2 items-center text-sm">
          <span>{{ selected.size }} selected</span>
          <Button size="sm" :disabled="!isOperator" @click="onRetry">Retry</Button>
          <Button v-if="isSysMgr" size="sm" variant="destructive" @click="onDiscard">Discard</Button>
          <Button v-if="isSysMgr && selected.size === 1 && currentSafe" size="sm" variant="outline" @click="onOpenEdit">
            Edit &amp; retry…
          </Button>
          <Button size="sm" variant="ghost" @click="clearSelection">Clear</Button>
        </div>
      </Card>
    </div>

    <div v-if="entry_name" class="flex-1 min-w-0 overflow-auto">
      <Card v-if="!detailEntry">
        <CardContent class="p-6 text-center text-muted-foreground">Loading…</CardContent>
      </Card>
      <Card v-else>
        <CardHeader class="flex flex-row items-center gap-2 flex-wrap">
          <StatusBadge :status="detailEntry.status" />
          <span class="text-xs text-muted-foreground">· queue {{ detailEntry.queue }}</span>
          <span class="text-xs text-muted-foreground">· attempts {{ detailEntry.attempts }}</span>
          <span class="text-2xs text-muted-foreground">{{ detailEntry.moved_at }}</span>
        </CardHeader>
        <CardContent class="space-y-4">
          <section>
            <h4 class="text-sm font-medium mb-2">Last error</h4>
            <p class="text-destructive text-sm">{{ detailEntry.last_error_type }}: {{ detailEntry.last_error_message }}</p>
            <details v-if="detailEntry.last_traceback">
              <summary class="cursor-pointer text-sm">Traceback</summary>
              <pre class="font-mono text-2xs bg-muted p-2 rounded max-h-96 overflow-auto mt-2">{{ detailEntry.last_traceback }}</pre>
            </details>
          </section>

          <section>
            <h4 class="text-sm font-medium mb-2 flex items-center gap-2">
              Original payload
              <Badge :variant="detailEntry.is_json_safe ? 'default' : 'secondary'">
                {{ detailEntry.is_json_safe ? "JSON-safe" : "non-JSON types" }}
              </Badge>
            </h4>
            <h5 class="text-2xs text-muted-foreground mt-2 mb-1">args</h5>
            <JsonViewer :value="detailEntry.payload_decoded?.args" />
            <h5 class="text-2xs text-muted-foreground mt-2 mb-1">kwargs</h5>
            <JsonViewer :value="detailEntry.payload_decoded?.kwargs" />
          </section>

          <section v-if="detailEntry.job">
            <h4 class="text-sm font-medium mb-2">Linked job</h4>
            <RouterLink :to="`/jobs/${detailEntry.job}`" class="text-primary hover:underline">{{ detailEntry.job }}</RouterLink>
          </section>

          <section v-if="detailEntry.reviewed_by">
            <h4 class="text-sm font-medium mb-2">Review</h4>
            <p class="text-sm">
              by <code class="font-mono">{{ detailEntry.reviewed_by }}</code> at
              <span class="text-2xs text-muted-foreground">{{ detailEntry.reviewed_at }}</span>
            </p>
            <p v-if="detailEntry.review_notes" class="text-sm">{{ detailEntry.review_notes }}</p>
          </section>

          <div class="flex gap-2">
            <Button :disabled="!isOperator" @click="onRetrySingle">Retry as-is</Button>
            <Button v-if="isSysMgr" variant="destructive" @click="onDiscardSingle">Discard</Button>
            <Button v-if="isSysMgr && detailEntry.is_json_safe" variant="outline" @click="onOpenEditSingle">
              Edit &amp; retry…
            </Button>
          </div>
        </CardContent>
      </Card>
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

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter, RouterLink } from "vue-router";
import { api, getList } from "@/api";
import { useUserRoles } from "@/stores/useUserRoles";
import { confirm } from "@/stores/useConfirm";
import { toast } from "@/stores/useToast";
import StatusBadge from "@/components/StatusBadge.vue";
import JsonViewer from "@/components/JsonViewer.vue";
import EditAndRetryModal from "@/components/EditAndRetryModal.vue";
import DlqDataTable from "@/components/DlqDataTable.vue";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const props = defineProps({ entry_name: String });
const router = useRouter();
const { entry_name } = toRefs(props);

const filters = reactive({ status: "PENDING_REVIEW", queue: "" });
const rows = ref([]);
const selected = ref(new Set());
const detailEntry = ref(null);
const editing = ref(null);

const { isOperator, isSysMgr } = useUserRoles();

async function reload() {
  const f = {};
  if (filters.status) f.status = filters.status;
  if (filters.queue) f.queue = filters.queue;
  rows.value = await getList("Conductor DLQ Entry", {
    fields: ["name", "queue", "status", "attempts", "last_error_type", "last_error_message", "moved_at"],
    filters: f,
    order_by: "moved_at desc",
    limit: 50,
  });
}

watch(filters, reload, { deep: true, immediate: true });

function open(name) { router.push({ path: `/dlq/${name}` }); }

function toggleSelect(name) {
  const next = new Set(selected.value);
  if (next.has(name)) next.delete(name);
  else next.add(name);
  selected.value = next;
}

function clearSelection() { selected.value = new Set(); }

function onFiltersChange(next) {
  Object.assign(filters, next);
}

watch(entry_name, async (id) => {
  detailEntry.value = null;
  if (!id) return;
  detailEntry.value = await api.getDlqEntry(id);
}, { immediate: true });

const currentSafe = computed(() => {
  if (selected.value.size !== 1) return false;
  const [name] = selected.value;
  if (detailEntry.value && detailEntry.value.name === name) return detailEntry.value.is_json_safe;
  return false;
});

async function onRetry() {
  const names = [...selected.value];
  if (!(await confirm(`Retry ${names.length} ${names.length === 1 ? "entry" : "entries"} as-is?`,
                       { title: "Retry DLQ entries", confirmText: "Retry" }))) return;
  try {
    await api.dlqRetry(names);
    toast(`${names.length} ${names.length === 1 ? "entry" : "entries"} retried`, "success");
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
    return;
  }
  clearSelection();
  reload();
  if (entry_name.value) detailEntry.value = await api.getDlqEntry(entry_name.value);
}

async function onDiscard() {
  const names = [...selected.value];
  if (!(await confirm(`Discard ${names.length} ${names.length === 1 ? "entry" : "entries"}? This cannot be undone.`,
                       { title: "Discard DLQ entries", confirmText: "Discard", danger: true }))) return;
  try {
    await api.dlqDiscard(names);
    toast(`${names.length} ${names.length === 1 ? "entry" : "entries"} discarded`, "success");
  } catch (e) {
    toast(`Discard failed: ${e.message}`, "error");
    return;
  }
  clearSelection();
  reload();
}

async function onOpenEdit() {
  const [name] = selected.value;
  const entry = await api.getDlqEntry(name);
  if (!entry.is_json_safe) {
    toast("Payload is not JSON-safe; edit-and-retry not available.", "warning");
    return;
  }
  editing.value = {
    name,
    args: entry.payload_decoded?.args || [],
    kwargs: entry.payload_decoded?.kwargs || {},
  };
}

async function onRetrySingle() {
  if (!(await confirm(`Retry this entry as-is?`,
                       { title: "Retry DLQ entry", confirmText: "Retry" }))) return;
  try {
    await api.dlqRetry([entry_name.value]);
    toast("Entry retried", "success");
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
    return;
  }
  reload();
  detailEntry.value = await api.getDlqEntry(entry_name.value);
}

async function onDiscardSingle() {
  if (!(await confirm(`Discard this entry? This cannot be undone.`,
                       { title: "Discard DLQ entry", confirmText: "Discard", danger: true }))) return;
  try {
    await api.dlqDiscard([entry_name.value]);
    toast("Entry discarded", "success");
  } catch (e) {
    toast(`Discard failed: ${e.message}`, "error");
    return;
  }
  reload();
  router.push({ path: "/dlq" });
}

async function onOpenEditSingle() {
  if (!detailEntry.value?.is_json_safe) {
    toast("Payload is not JSON-safe; edit-and-retry not available.", "warning");
    return;
  }
  editing.value = {
    name: entry_name.value,
    args: detailEntry.value.payload_decoded?.args || [],
    kwargs: detailEntry.value.payload_decoded?.kwargs || {},
  };
}

async function onEditSaved(newId) {
  toast(`Re-enqueued as ${String(newId).slice(0, 8)}…`, "success");
  editing.value = null;
  clearSelection();
  reload();
}
</script>
```

- [ ] **Step 5: Verify build and visual**

```bash
yarn build && yarn dev
```

Open `/dlq`. Verify:
- Filter row works (status select + queue input both refetch from server)
- Sortable column headers work (click "Moved at" — direction indicator appears)
- Pagination shows when there are more than 25 rows
- Checkboxes select rows; bulk-action card appears with Retry / Discard / Edit&Retry / Clear
- Clicking a row opens detail card on the right with retry / discard / edit buttons
- Edit & retry opens shadcn Dialog with two textareas; invalid JSON shows the inline error
- Confirm dialogs use AlertDialog
- Toasts appear via Sonner

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/pages/DlqPage.vue dashboard/src/components/DlqDataTable.vue dashboard/src/components/EditAndRetryModal.vue dashboard/src/components/ui/dialog/ dashboard/src/components/ui/checkbox/ dashboard/src/components/ui/textarea/
git commit -m "feat(dashboard): redesign DLQ (DataTable + bulk actions + Dialog editor)"
```

---

## Task 18: Final integration verification

**Files:** none (verification-only)

- [ ] **Step 1: Run a clean build**

```bash
cd /Users/osamamuhammed/frappe_15/apps/conductor/dashboard
rm -rf node_modules/.vite ../conductor/public/dashboard
yarn install
yarn build
```

Expected: build succeeds; bundle lands in `../conductor/public/dashboard/`; `../conductor/www/conductor-dashboard.html` is updated.

- [ ] **Step 2: Run bench build**

```bash
cd /Users/osamamuhammed/frappe_15
bench build --app conductor
```

Expected: bench reports the conductor app's assets built successfully.

- [ ] **Step 3: Visit the dashboard on a live site**

Pick any conductor-installed site and visit `http://<site>/conductor-dashboard` in a browser.

Visit each page in turn: `/overview`, `/feed`, `/jobs`, `/dlq`, `/schedules`, `/workers`, `/workflows`. For each page, verify:
- Loads without console errors (open devtools)
- Sidebar nav is visible and the active route is highlighted
- Mode toggle works and persists across reloads
- Data appears (if no data, the empty-state text shows)

- [ ] **Step 4: Smoke a real flow**

```bash
bench --site <site> conductor doctor --demo
```

This enqueues a demo job. Open `/jobs` in the browser and confirm the job appears in real-time without page reload (useDetailSubscription / useAutoPolling still wired).

- [ ] **Step 5: Verify retry / cancel still work**

Pick a `FAILED` or `DLQ` job in the dashboard. Click Retry. Confirm the AlertDialog appears, accept it, watch a Sonner toast appear with the new job ID, and confirm the job list updates.

- [ ] **Step 6: Verify dark + light themes on every page**

Toggle to Dark mode in the header. Walk through all 7 pages; confirm none have visible white-on-white or black-on-black regressions. Toggle back to Light mode; same check.

- [ ] **Step 7: Run the Python suite to confirm nothing else regressed**

```bash
/Users/osamamuhammed/frappe_15/env/bin/pytest /Users/osamamuhammed/frappe_15/apps/conductor/tests
```

Expected: all tests pass. If anything fails, the failure is unrelated to this work — investigate and stop.

- [ ] **Step 8: Open the PR**

```bash
git push -u origin feat/dashboard-shadcn-vue
gh pr create --base develop --title "feat(dashboard): shadcn-vue redesign" --body "$(cat <<'EOF'
## Summary

- Rebuilds the Conductor dashboard with shadcn-vue primitives (sidebar, cards, tables, tabs, dialogs, sonner)
- Adds dark / light / system theme toggle with persisted preference
- Preserves every existing behavior — data wiring, real-time updates, retry / cancel / run-now / edit-and-retry

## Test plan

- [ ] `yarn build` from `dashboard/` succeeds
- [ ] `bench build --app conductor` succeeds
- [ ] Visit `/conductor-dashboard` and click through all 7 pages
- [ ] Toggle dark / light / system; preference persists across reloads
- [ ] Sidebar collapses to icon-only and back
- [ ] `bench conductor doctor --demo` produces a job that appears in `/jobs` without reload
- [ ] Retry a failed job; AlertDialog confirms, Sonner toast confirms success
- [ ] DLQ bulk-select; retry / discard / edit-and-retry all work
- [ ] No new console errors

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

> **Note:** confirm with the user before pushing or opening the PR — the user did not pre-authorize a push. If they say go, run the commands above; otherwise stop after Step 7.

---

## Self-review (run by the plan author after writing)

Spec coverage:

| Spec section | Implemented in task |
|---|---|
| Stack additions (deps) | T1, T2 (`tw-animate-css`), T3 |
| Theming variables | T2 |
| Color mode toggle | T3 |
| Shell (sidebar + header) | T6 |
| Toast retarget (vue-sonner) | T4, T6 (commit) |
| Confirm retarget (AlertDialog) | T5, T6 (commit) |
| StatusBadge wrap | T7 |
| NumberCard wrap | T8 |
| Overview page | T9 |
| Live Feed page | T10 |
| Workers page | T11 |
| Workflows page | T12 |
| WorkflowRunDetail page | T13 |
| Schedules page (Sheet) | T14 |
| JobsDataTable component | T15 |
| Jobs page | T16 |
| DlqDataTable component | T17 |
| DLQ page + EditAndRetryModal | T17 |
| Final verification (yarn + bench + smoke) | T18 |

All spec sections covered. Tanstack sort + pagination + faceted filter (spec §5 Jobs / §6 components / §11 risks) is delivered in Tasks 15 and 17. Tasks 11, 12, 13, and 17's EditAndRetryModal use property names verified against the actual existing source files — no hedge instructions remain. No placeholders.

Plan complete.
