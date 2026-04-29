<template>
  <pre class="font-mono text-xs bg-slate-50 p-3 rounded max-h-96 overflow-auto whitespace-pre-wrap break-words">{{ formatted }}</pre>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ value: { default: null } });

const formatted = computed(() => {
  try   { return JSON.stringify(props.value, null, 2); }
  catch { return String(props.value); }
});
</script>
