<template>
  <div class="px-2">
    <div v-if="!state" class="p-6 text-center text-slate-400">Loading…</div>
    <div v-else>
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <NumberCard :value="totalDepth" label="Total queue depth" @click="go('/jobs')" />
        <NumberCard :value="aliveWorkers" label="Active workers" @click="go('/workers')" />
        <NumberCard :value="dlqPending" label="DLQ pending review" @click="go('/dlq')" />
        <NumberCard :value="schedulesEnabled" label="Schedules enabled" @click="go('/schedules')" />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <QueueChart title="Queue depth by queue" :data="queueDepthData" />
        <QueueChart title="DLQ status counts" :data="dlqData" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "../stores/useDashboardState";
import NumberCard from "../components/NumberCard.vue";
import QueueChart from "../components/QueueChart.vue";

const router = useRouter();
const { state } = useAutoPolling();

const totalDepth = computed(() =>
  (state.value?.queues || []).reduce((sum, q) => sum + (q.depth_redis || 0), 0)
);
const aliveWorkers = computed(() => state.value?.worker_summary?.alive ?? 0);
const dlqPending = computed(() => state.value?.dlq_summary?.pending_review ?? 0);
const schedulesEnabled = computed(() => state.value?.schedule_summary?.enabled_count ?? 0);

const queueDepthData = computed(() =>
  (state.value?.queues || []).map(q => ({ label: q.name, value: q.depth_redis }))
);

const dlqData = computed(() => {
  const s = state.value?.dlq_summary || {};
  return [
    { label: "Pending", value: s.pending_review || 0 },
    { label: "Retried", value: s.retried || 0 },
    { label: "Discarded", value: s.discarded || 0 },
  ];
});

function go(path) { router.push(path); }
</script>
