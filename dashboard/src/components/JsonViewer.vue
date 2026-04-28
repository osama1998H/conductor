<template>
  <pre class="json">{{ formatted }}</pre>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ value: { default: null } });

const formatted = computed(() => {
  try   { return JSON.stringify(props.value, null, 2); }
  catch { return String(props.value); }
});
</script>

<style scoped>
.json {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 12px;
  background: #f8fafc;
  padding: 12px;
  border-radius: 4px;
  max-height: 400px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
