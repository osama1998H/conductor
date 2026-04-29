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
              'cursor-pointer',
              row.name === worker_id ? 'bg-indigo-100' : 'hover:bg-slate-50',
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

    <div class="flex-1 min-w-0 border-l border-slate-300 pl-4 overflow-auto" v-if="worker_id">
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

<script setup>
import { ref, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList } from "../api";
import StatusBadge from "../components/StatusBadge.vue";

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
    // newer heartbeat first within the same status
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
