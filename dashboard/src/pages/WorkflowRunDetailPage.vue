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
  <div v-if="data && data.run" class="run-detail">
    <header>
      <button @click="router.back()">&laquo; Back</button>
      <h2>{{ data.run.name }}</h2>
      <div class="meta">
        <strong>Workflow:</strong> {{ data.run.workflow }} (v{{ data.run.definition_version }})
        <StatusBadge :status="data.run.status" />
        <button v-if="canCancel" @click="cancel" class="cancel-btn">Cancel run</button>
      </div>
    </header>

    <section>
      <h3>DAG</h3>
      <MermaidDag :snapshot="data.snapshot" :steps="data.steps" />
    </section>

    <section>
      <h3>Step runs</h3>
      <table>
        <thead><tr><th>Step</th><th>Type</th><th>Status</th><th>Started</th><th>Finished</th><th>Job</th></tr></thead>
        <tbody>
          <tr v-for="s in data.steps" :key="s.name">
            <td>{{ s.step_id }}</td>
            <td>{{ s.is_compensation ? 'compensation' : 'forward' }}</td>
            <td><StatusBadge :status="s.status" /></td>
            <td>{{ s.started_at || '—' }}</td>
            <td>{{ s.finished_at || '—' }}</td>
            <td>
              <router-link v-if="s.job" :to="`/jobs/${s.job}`">{{ s.job }}</router-link>
              <span v-else>—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="data.run.last_error">
      <h3>Last error</h3>
      <pre>{{ data.run.last_error }}</pre>
    </section>
  </div>
</template>

<style scoped>
.run-detail header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.cancel-btn { background: #ef4444; color: white; border: 0; padding: 6px 12px; border-radius: 4px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 6px 10px; border-bottom: 1px solid #eee; text-align: left; }
pre { background: #f3f4f6; padding: 12px; overflow-x: auto; }
</style>
