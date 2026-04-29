<template>
  <span :class="['text-2xs px-2 py-0.5 rounded-full font-medium', toneClasses]">{{ status }}</span>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ status: String });

const tone = computed(() => {
  switch (props.status) {
    case "SUCCEEDED": return "green";
    case "RUNNING":
    case "ALIVE": return "blue";
    case "QUEUED":
    case "SCHEDULED_RETRY": return "yellow";
    case "FAILED":
    case "DLQ":
    case "TIMED_OUT":
    case "DISPATCH_FAILED":
    case "STALE": return "red";
    case "CANCELLED":
    case "GONE": return "grey";
    default: return "grey";
  }
});

const toneClasses = computed(() => {
  switch (tone.value) {
    case "green":  return "bg-green-100 text-green-800";
    case "blue":   return "bg-blue-100 text-blue-900";
    case "yellow": return "bg-amber-100 text-amber-800";
    case "red":    return "bg-red-100 text-red-800";
    case "grey":
    default:       return "bg-slate-100 text-slate-600";
  }
});
</script>
