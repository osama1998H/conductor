<template>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger as-child>
        <span
          class="relative inline-flex h-2.5 w-2.5 items-center justify-center"
          role="status"
          :aria-label="headline"
        >
          <span
            v-if="status === 'healthy'"
            class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"
            :class="dotColor"
          />
          <span class="relative inline-flex h-2.5 w-2.5 rounded-full" :class="dotColor" />
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom">
        <div class="text-xs">
          <div class="font-medium">{{ headline }}</div>
          <div class="text-muted-foreground">{{ detail }}</div>
        </div>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>

<script setup>
import { computed } from "vue";
import { useAutoPolling } from "@/stores/useDashboardState";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

const { state, error } = useAutoPolling();

const summary = computed(() => state.value?.worker_summary);

const status = computed(() => {
  if (error.value) return "error";
  if (!summary.value) return "loading";
  if ((summary.value.alive ?? 0) > 0) return "healthy";
  if ((summary.value.total ?? 0) > 0) return "stale";
  return "down";
});

const COLOR_BY_STATUS = {
  healthy: "bg-green-500",
  stale: "bg-orange-500",
  down: "bg-red-500",
  error: "bg-red-500",
  loading: "bg-muted-foreground",
};

const HEADLINE_BY_STATUS = {
  healthy: "Conductor running",
  stale: "Conductor not running",
  down: "No workers registered",
  error: "Health check failed",
  loading: "Checking conductor…",
};

const dotColor = computed(() => COLOR_BY_STATUS[status.value]);
const headline = computed(() => HEADLINE_BY_STATUS[status.value]);

const detail = computed(() => {
  if (status.value === "error") return "Dashboard API unreachable.";
  if (status.value === "loading") return "Awaiting first health check…";
  const s = summary.value || {};
  const alive = s.alive ?? 0;
  const stale = s.stale ?? 0;
  const gone = s.gone ?? 0;
  if (status.value === "down") return "Run `bench conductor worker` to start processing jobs.";
  if (status.value === "stale") return `0 alive · ${stale} stale · ${gone} gone — workers stopped.`;
  return `${alive} alive · ${stale} stale · ${gone} gone`;
});
</script>
