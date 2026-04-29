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
