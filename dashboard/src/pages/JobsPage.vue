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

// detail is a ref; Vue auto-unwraps in the template so we use "detail.x" not "detail.value.x"
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
