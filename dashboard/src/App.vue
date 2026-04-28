<template>
  <div class="conductor-shell">
    <nav class="tabs">
      <router-link to="/overview">Overview</router-link>
      <router-link to="/feed">Live Feed</router-link>
      <router-link to="/jobs">Jobs</router-link>
      <router-link to="/dlq">DLQ</router-link>
      <router-link to="/schedules">Schedules</router-link>
      <router-link to="/workers">Workers</router-link>
    </nav>
    <main><router-view /></main>
  </div>
</template>

<script setup>
</script>

<style scoped>
.conductor-shell {
  font-family: system-ui, sans-serif;
}

.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid #ddd;
  padding: 0 16px;
}

.tabs a {
  padding: 8px 12px;
  text-decoration: none;
  color: #555;
  border-bottom: 2px solid transparent;
}

.tabs a.router-link-active {
  color: #2563eb;
  border-bottom-color: #2563eb;
  font-weight: 500;
}

main {
  padding: 16px;
}
</style>

<!-- Global styles (unscoped): apply to filter-bar buttons across all pages. -->
<style>
.conductor-shell .filters button {
  padding: 4px 12px;
  font-size: 13px;
  background: #fff;
  color: #1e293b;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.conductor-shell .filters button:hover {
  border-color: #2563eb;
  background: #f8fafc;
}

.conductor-shell .filters button:active {
  background: #eff6ff;
}

.conductor-shell .filters button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
