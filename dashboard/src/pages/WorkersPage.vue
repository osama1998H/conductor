<template>
  <div class="workers-page">
    <div class="master">
      <div class="filters">
        <button @click="reload">Refresh</button>
      </div>
      <table class="worker-list">
        <thead>
          <tr>
            <th>Status</th>
            <th>Worker</th>
            <th>Host</th>
            <th>PID</th>
            <th>Queues</th>
            <th>HB age</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in sortedRows" :key="row.name" :class="{ active: row.name === worker_id }"
            @click="open(row.name)">
            <td>
              <StatusBadge :status="row.status" />
            </td>
            <td class="mono">{{ row.name }}</td>
            <td>{{ row.host }}</td>
            <td>{{ row.pid }}</td>
            <td>{{ parseQueues(row.queues) }}</td>
            <td class="ts">{{ heartbeatAge(row.last_heartbeat) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="empty">No workers registered.</div>
    </div>

    <div class="detail" v-if="worker_id">
      <div v-if="!detail" class="empty">Loading…</div>
      <div v-else>
        <header>
          <StatusBadge :status="detail.status" />
          <code>{{ detail.name }}</code>
          <span>· {{ detail.host }}:{{ detail.pid }}</span>
          <span v-if="detail.conductor_version">· v{{ detail.conductor_version }}</span>
        </header>

        <section>
          <h4>Queues</h4>
          <p class="mono">{{ parseQueues(detail.queues) }}</p>
        </section>

        <section>
          <h4>Heartbeat</h4>
          <p>Last beat at <span class="ts">{{ detail.last_heartbeat }}</span> ({{ detail.heartbeat_age_seconds }}s ago)
          </p>
          <p>Started at <span class="ts">{{ detail.started_at }}</span></p>
        </section>

        <section v-if="detail.current_job">
          <h4>Currently executing</h4>
          <router-link :to="`/jobs/${detail.current_job}`" class="mono">{{ detail.current_job }}</router-link>
          <span v-if="currentJobStatus"> ·
            <StatusBadge :status="currentJobStatus" />
          </span>
        </section>

        <section>
          <h4>Recent jobs handled</h4>
          <table v-if="detail.recent_jobs?.length" class="runs">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Method</th>
                <th>Queue</th>
                <th>Status</th>
                <th>Finished</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in detail.recent_jobs" :key="r.job_id">
                <td><router-link :to="`/jobs/${r.job_id}`" class="mono">{{ r.job_id.slice(0, 8) }}…</router-link></td>
                <td class="mono">{{ r.method }}</td>
                <td>{{ r.queue }}</td>
                <td>
                  <StatusBadge :status="r.status" />
                </td>
                <td class="ts">{{ r.finished_at }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty">No recent jobs.</div>
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

<style scoped>
.workers-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 100px);
}

.master {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.detail {
  flex: 1;
  min-width: 0;
  border-left: 1px solid #ddd;
  padding-left: 16px;
  overflow: auto;
}

.filters {
  margin-bottom: 12px;
}

.worker-list {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.worker-list th,
.worker-list td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #eee;
}

.worker-list tbody tr {
  cursor: pointer;
}

.worker-list tbody tr:hover {
  background: #f8fafc;
}

.worker-list tbody tr.active {
  background: #e0e7ff;
}

.mono,
code {
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.ts {
  font-size: 11px;
  color: #64748b;
}

.empty {
  color: #94a3b8;
  padding: 12px;
  text-align: center;
}

header {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

section {
  margin-top: 16px;
}

section h4 {
  margin-bottom: 8px;
}

.runs {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.runs th,
.runs td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #eee;
}
</style>
