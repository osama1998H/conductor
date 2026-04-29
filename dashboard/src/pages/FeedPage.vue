<template>
  <div class="px-2">
    <div class="flex gap-4 items-center mb-4">
      <h2 class="m-0">Live Feed</h2>
      <label class="flex gap-1 items-center text-sm text-slate-600 cursor-pointer">
        <input type="checkbox" v-model="paused" /> Pause updates
      </label>
      <span class="text-xs text-slate-400">{{ paused ? "(showing snapshot)" : `(updating; ${rows.length} jobs)` }}</span>
    </div>

    <div class="max-h-[calc(100vh-180px)] overflow-y-auto">
      <div
        v-for="row in rows"
        :key="row.job_id"
        class="flex gap-3 items-center px-3 py-2 border-b border-slate-200 cursor-pointer text-sm hover:bg-slate-50"
        @click="open(row.job_id)"
      >
        <span class="font-mono text-2xs text-slate-500 min-w-[140px]">{{ formatTime(row.enqueued_at) }}</span>
        <StatusBadge :status="row.status" />
        <span class="text-xs text-slate-600 min-w-20">{{ row.queue }}</span>
        <code class="font-mono text-xs flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{{ row.method }}</code>
        <span class="font-mono text-2xs text-slate-400">{{ row.job_id.slice(0, 8) }}…</span>
      </div>
      <div v-if="!rows.length" class="p-6 text-center text-slate-400">No jobs yet.</div>
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
