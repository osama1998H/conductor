<template>
  <div class="space-y-4">
    <div class="flex items-center gap-4">
      <h2 class="text-xl font-semibold">Live Feed</h2>
      <div class="flex items-center gap-2">
        <Switch id="pause" v-model:checked="paused" />
        <Label for="pause">Pause updates</Label>
      </div>
      <span class="text-xs text-muted-foreground">
        {{ paused ? "(showing snapshot)" : `(updating; ${rows.length} jobs)` }}
      </span>
    </div>

    <Card>
      <ScrollArea class="h-[calc(100vh-220px)]">
        <div
          v-for="row in rows"
          :key="row.job_id"
          class="flex items-center gap-3 px-4 py-2 border-b cursor-pointer text-sm hover:bg-muted/50"
          @click="open(row.job_id)"
        >
          <span class="font-mono text-2xs text-muted-foreground min-w-[140px]">{{ formatTime(row.enqueued_at) }}</span>
          <StatusBadge :status="row.status" />
          <span class="text-xs text-muted-foreground min-w-20">{{ row.queue }}</span>
          <code class="font-mono text-xs flex-1 min-w-0 truncate">{{ row.method }}</code>
          <span class="font-mono text-2xs text-muted-foreground">{{ row.job_id.slice(0, 8) }}…</span>
        </div>
        <div v-if="!rows.length" class="p-6 text-center text-muted-foreground">No jobs yet.</div>
      </ScrollArea>
    </Card>
  </div>
</template>

<script setup>
import { ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { useAutoPolling } from "@/stores/useDashboardState";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";

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
