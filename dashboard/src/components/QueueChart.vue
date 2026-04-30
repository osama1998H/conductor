<template>
  <div v-if="!data.length" class="text-muted-foreground p-4 text-center text-xs">No data</div>
  <div v-else class="space-y-1">
    <div
      v-for="row in data"
      :key="row.label"
      class="grid grid-cols-[100px_1fr_50px] gap-3 items-center py-1 text-xs"
    >
      <div class="text-foreground overflow-hidden text-ellipsis whitespace-nowrap">{{ row.label }}</div>
      <div class="bg-muted h-3.5 rounded-sm overflow-hidden">
        <div
          class="bg-primary h-full transition-[width] duration-300"
          :style="{ width: pct(row.value) + '%' }"
        ></div>
      </div>
      <div class="text-right text-foreground font-medium">{{ row.value }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({
  data: { type: Array, default: () => [] },
});

const max = computed(() => Math.max(1, ...props.data.map(d => d.value || 0)));
function pct(v) { return Math.max(0, Math.min(100, ((v || 0) / max.value) * 100)); }
</script>
