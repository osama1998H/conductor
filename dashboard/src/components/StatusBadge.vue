<template>
  <Badge :class="toneClasses">{{ status }}</Badge>
</template>

<script setup>
import { computed } from "vue";
import { Badge } from "@/components/ui/badge";

const props = defineProps({ status: String });

const TONE_BY_STATUS = {
  SUCCEEDED: "green",
  RUNNING: "blue",
  ALIVE: "blue",
  QUEUED: "yellow",
  SCHEDULED_RETRY: "yellow",
  FAILED: "red",
  DLQ: "red",
  TIMED_OUT: "red",
  DISPATCH_FAILED: "red",
  STALE: "red",
  CANCELLED: "grey",
  GONE: "grey",
};

const TONE_TO_CLASSES = {
  green:  "bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-300 border-transparent",
  blue:   "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-300 border-transparent",
  yellow: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300 border-transparent",
  red:    "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-300 border-transparent",
  grey:   "bg-muted text-muted-foreground border-transparent",
};

const toneClasses = computed(() => TONE_TO_CLASSES[TONE_BY_STATUS[props.status] || "grey"]);
</script>
