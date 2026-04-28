<template>
  <div class="jobs-page">
    <div class="master">
      <div class="filters">
        <select v-model="filters.status">
          <option value="">All statuses</option>
          <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
        </select>
        <input v-model="filters.method" placeholder="method contains…" />
        <input v-model="filters.queue"  placeholder="queue" />
        <button @click="reload">Refresh</button>
      </div>

      <table class="job-list">
        <thead>
          <tr>
            <th>Status</th>
            <th>Method</th>
            <th>Queue</th>
            <th>Attempt</th>
            <th>Enqueued</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.job_id"
            :class="{ active: row.job_id === job_id }"
            @click="open(row.job_id)"
          >
            <td><StatusBadge :status="row.status" /></td>
            <td class="mono">{{ row.method }}</td>
            <td>{{ row.queue }}</td>
            <td>{{ row.attempt }}</td>
            <td class="ts">{{ row.enqueued_at }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="!rows.length" class="empty">No jobs match.</div>
    </div>

    <div class="detail" v-if="job_id">
      <div v-if="!detail" class="empty">Loading…</div>
      <div v-else>
        <header>
          <StatusBadge :status="detail.status" />
          <code>{{ detail.method }}</code>
          <span>· attempt {{ detail.attempt }}/{{ detail.max_attempts }}</span>
          <span>· queue {{ detail.queue }}</span>
        </header>

        <nav class="subtabs">
          <button :class="{ active: subtab === 'overview' }" @click="subtab = 'overview'">Overview</button>
          <button :class="{ active: subtab === 'runs' }"     @click="subtab = 'runs'">Runs ({{ detail.runs?.length || 0 }})</button>
          <button :class="{ active: subtab === 'args' }"     @click="subtab = 'args'">Args</button>
          <button :class="{ active: subtab === 'trace' }"    @click="subtab = 'trace'">Trace</button>
        </nav>

        <section v-if="subtab === 'overview'">
          <p v-if="detail.last_error_message" class="error">
            {{ detail.last_error_type }}: {{ detail.last_error_message }}
          </p>
          <details v-if="detail.last_traceback">
            <summary>Traceback</summary>
            <pre class="tb">{{ detail.last_traceback }}</pre>
          </details>
          <div class="actions">
            <button @click="onRetry"  :disabled="!canRetry">Retry</button>
            <button @click="onCancel" :disabled="!canCancel">Cancel</button>
          </div>
        </section>

        <section v-if="subtab === 'runs'">
          <table class="runs">
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Duration</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in (detail.runs || [])" :key="r.attempt_number">
                <td>{{ r.attempt_number }}</td>
                <td><StatusBadge :status="r.status" /></td>
                <td class="ts">{{ r.started_at }}</td>
                <td class="ts">{{ r.finished_at }}</td>
                <td>{{ r.duration_ms }}ms</td>
                <td>{{ r.error_type }}</td>
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

        <section v-if="subtab === 'trace'">
          <p>trace_id: <code>{{ detail.trace_id || '(none)' }}</code></p>
          <p v-if="detail.runs?.[0]?.sentry_url">
            <a :href="detail.runs[0].sentry_url" target="_blank">Sentry</a>
          </p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList, userRoles } from "../api";
import { useDetailSubscription } from "../stores/useDetailSubscription";
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
const rows    = ref([]);
const subtab  = ref("overview");

async function reload() {
  const f = {};
  if (filters.status) f.status = filters.status;
  if (filters.queue)  f.queue  = filters.queue;
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

// detail is a ref; Vue auto-unwraps in the template so we use "detail.x" not "detail.value.x"
const { data: detail, refetch: refetchDetail } = useDetailSubscription(
  "Conductor Job",
  "conductor:job",
  job_id,
  () => api.getJob(job_id.value),
);

const roles      = userRoles();
const isOperator = roles.includes("Conductor Operator") || roles.includes("System Manager");

const canRetry = computed(() =>
  isOperator &&
  ["FAILED", "TIMED_OUT", "DLQ", "CANCELLED", "DISPATCH_FAILED"].includes(detail.value?.status)
);

const canCancel = computed(() =>
  isOperator &&
  ["QUEUED", "RUNNING", "SCHEDULED_RETRY"].includes(detail.value?.status)
);

async function onRetry() {
  if (!confirm(`Retry ${job_id.value}?`)) return;
  const newId = await api.retryJob(job_id.value);
  alert(`Re-enqueued as ${newId}`);
  reload();
}

async function onCancel() {
  if (!confirm(`Cancel ${job_id.value}?`)) return;
  await api.cancelJob(job_id.value);
  refetchDetail();
}
</script>

<style scoped>
.jobs-page { display: flex; gap: 16px; height: calc(100vh - 100px); }
.master    { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.detail    { flex: 1; min-width: 0; border-left: 1px solid #ddd; padding-left: 16px; overflow: auto; }

.filters { display: flex; gap: 8px; margin-bottom: 12px; }
.filters select,
.filters input  { padding: 4px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 13px; }

.job-list                  { width: 100%; border-collapse: collapse; font-size: 12px; }
.job-list th,
.job-list td               { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }
.job-list tbody tr         { cursor: pointer; }
.job-list tbody tr:hover   { background: #f8fafc; }
.job-list tbody tr.active  { background: #e0e7ff; }

.mono, code { font-family: ui-monospace, SFMono-Regular, monospace; }
.ts         { font-size: 11px; color: #64748b; }
.empty      { color: #94a3b8; padding: 12px; text-align: center; }

header { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }

.subtabs               { display: flex; gap: 4px; border-bottom: 1px solid #ddd; margin-bottom: 12px; }
.subtabs button        { padding: 6px 10px; background: transparent; border: 0; border-bottom: 2px solid transparent; cursor: pointer; }
.subtabs button.active { border-bottom-color: #2563eb; color: #2563eb; }

.error { color: #991b1b; }
.tb    { font-family: ui-monospace, monospace; font-size: 11px; background: #fee; padding: 8px; border-radius: 4px; max-height: 400px; overflow: auto; }

.actions            { margin-top: 16px; display: flex; gap: 8px; }
.actions button          { padding: 6px 14px; background: #2563eb; color: white; border: 0; border-radius: 4px; cursor: pointer; }
.actions button:disabled { background: #cbd5e1; cursor: not-allowed; }

.runs        { width: 100%; border-collapse: collapse; font-size: 12px; }
.runs th,
.runs td     { text-align: left; padding: 4px 8px; border-bottom: 1px solid #eee; }
</style>
