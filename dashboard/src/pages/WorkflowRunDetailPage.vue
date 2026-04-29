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
