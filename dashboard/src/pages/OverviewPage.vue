<template>
  <div class="space-y-6">
    <div v-if="!state" class="p-6 text-center text-muted-foreground">Loading…</div>
    <div v-else class="space-y-6">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <NumberCard :value="totalDepth" label="Total queue depth" @click="go('/jobs')" />
        <NumberCard :value="aliveWorkers" label="Active workers" @click="go('/workers')" />
        <NumberCard :value="dlqPending" label="DLQ pending review" @click="go('/dlq')" />
        <NumberCard :value="schedulesEnabled" label="Schedules enabled" @click="go('/schedules')" />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Queue depth by queue</CardTitle>
          </CardHeader>
          <CardContent>
            <QueueChart :data="queueDepthData" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>DLQ status counts</CardTitle>
          </CardHeader>
          <CardContent>
            <QueueChart :data="dlqData" />
          </CardContent>
        </Card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "@/stores/useDashboardState";
import NumberCard from "@/components/NumberCard.vue";
import QueueChart from "@/components/QueueChart.vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
