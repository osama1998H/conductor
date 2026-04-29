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
  <div class="workflows-page">
    <h2>Workflows</h2>
    <table class="wf-list">
      <thead>
        <tr><th>Name</th><th>Version</th><th>Active</th><th>24h</th><th>Last Bump</th></tr>
      </thead>
      <tbody>
        <tr v-for="w in workflows" :key="w.workflow_name"
            :class="{ active: selectedWorkflow === w.workflow_name }"
            @click="selectWorkflow(w.workflow_name)">
          <td>{{ w.workflow_name }}</td>
          <td>v{{ w.version }}</td>
          <td>{{ w.active_runs }}</td>
          <td>{{ w.recent_runs_24h }}</td>
          <td>{{ w.last_version_bumped_at || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <h3 v-if="selectedWorkflow">Runs of {{ selectedWorkflow }}</h3>
    <h3 v-else>Recent Runs (all workflows)</h3>
    <table class="run-list">
      <thead>
        <tr><th>Run ID</th><th>Workflow</th><th>Status</th><th>Started</th><th>Finished</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in recentRuns" :key="r.name">
          <td><router-link :to="`/workflows/runs/${r.name}`">{{ r.name }}</router-link></td>
          <td>{{ r.workflow }} (v{{ r.definition_version }})</td>
          <td><StatusBadge :status="r.status" /></td>
          <td>{{ r.started_at || '—' }}</td>
          <td>{{ r.finished_at || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.wf-list, .run-list { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
.wf-list th, .wf-list td, .run-list th, .run-list td { padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }
.wf-list tr.active { background: #fef9c3; cursor: pointer; }
.wf-list tr:hover { background: #f9fafb; cursor: pointer; }
</style>
