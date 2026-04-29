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
            'cursor-pointer',
            selectedWorkflow === w.workflow_name ? 'bg-yellow-100' : 'hover:bg-slate-50',
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
