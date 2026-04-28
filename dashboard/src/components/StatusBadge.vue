<template>
  <span :class="['badge', `badge-${tone}`]">{{ status }}</span>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ status: String });

const tone = computed(() => {
  switch (props.status) {
    case "SUCCEEDED":       return "green";
    case "RUNNING":         return "blue";
    case "QUEUED":
    case "SCHEDULED_RETRY": return "yellow";
    case "FAILED":
    case "DLQ":
    case "TIMED_OUT":
    case "DISPATCH_FAILED": return "red";
    case "CANCELLED":       return "grey";
    default:                return "grey";
  }
});
</script>

<style scoped>
.badge        { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 500; }
.badge-green  { background: #dcfce7; color: #166534; }
.badge-blue   { background: #dbeafe; color: #1e40af; }
.badge-yellow { background: #fef3c7; color: #854d0e; }
.badge-red    { background: #fee2e2; color: #991b1b; }
.badge-grey   { background: #f1f5f9; color: #475569; }
</style>
