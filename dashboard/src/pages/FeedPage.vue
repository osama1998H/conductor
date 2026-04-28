<template>
  <div class="feed-page">
    <div class="header-bar">
      <h2>Live Feed</h2>
      <label class="pause">
        <input type="checkbox" v-model="paused" /> Pause updates
      </label>
      <span class="hint">{{ paused ? "(showing snapshot)" : `(updating; ${rows.length} jobs)` }}</span>
    </div>

    <div class="feed">
      <div v-for="row in rows" :key="row.job_id"
           class="feed-row"
           @click="open(row.job_id)">
        <span class="ts">{{ formatTime(row.enqueued_at) }}</span>
        <StatusBadge :status="row.status" />
        <span class="queue">{{ row.queue }}</span>
        <code class="method">{{ row.method }}</code>
        <span class="job-id mono">{{ row.job_id.slice(0, 8) }}…</span>
      </div>
      <div v-if="!rows.length" class="empty">No jobs yet.</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "../stores/useDashboardState";
import StatusBadge from "../components/StatusBadge.vue";

const router = useRouter();
const { state } = useAutoPolling();

const paused = ref(false);
const frozenRows = ref([]);

function formatTime(ts) {
  if (!ts) return "";
  return String(ts).replace("T", " ").slice(0, 19);
}

const rows = computed(() => {
  if (paused.value) return frozenRows.value;
  return state.value?.feed_recent || [];
});

watch(paused, (now) => {
  if (now) frozenRows.value = [...(state.value?.feed_recent || [])];
});

function open(id) { router.push({ path: `/jobs/${id}` }); }
</script>

<style scoped>
.feed-page { padding: 0 8px; }
.header-bar { display: flex; gap: 16px; align-items: center; margin-bottom: 16px; }
.header-bar h2 { margin: 0; }
.pause { display: flex; gap: 4px; align-items: center; font-size: 13px; color: #475569; cursor: pointer; }
.hint { font-size: 12px; color: #94a3b8; }
.feed { max-height: calc(100vh - 180px); overflow-y: auto; }
.feed-row { display: flex; gap: 12px; align-items: center; padding: 8px 12px;
            border-bottom: 1px solid #eee; cursor: pointer; font-size: 13px; }
.feed-row:hover { background: #f8fafc; }
.ts { font-family: ui-monospace, monospace; font-size: 11px; color: #64748b; min-width: 140px; }
.queue { font-size: 12px; color: #475569; min-width: 80px; }
.method { font-family: ui-monospace, monospace; font-size: 12px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job-id { font-size: 11px; color: #94a3b8; }
.mono { font-family: ui-monospace, monospace; }
.empty { padding: 24px; text-align: center; color: #94a3b8; }
</style>
