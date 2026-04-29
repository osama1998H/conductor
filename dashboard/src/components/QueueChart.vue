<template>
  <div class="bg-white border border-slate-200 rounded-md p-4">
    <div class="text-sm font-medium text-slate-600 mb-3">{{ title }}</div>
    <div v-if="!data.length" class="text-slate-400 p-4 text-center text-xs">No data</div>
    <div v-else>
      <div
        v-for="row in data"
        :key="row.label"
        class="grid grid-cols-[100px_1fr_50px] gap-3 items-center py-1 text-xs"
      >
        <div class="text-slate-600 overflow-hidden text-ellipsis whitespace-nowrap">{{ row.label }}</div>
        <div class="bg-slate-100 h-3.5 rounded-sm overflow-hidden">
          <div
            class="bg-primary h-full transition-[width] duration-300"
            :style="{ width: pct(row.value) + '%' }"
          ></div>
        </div>
        <div class="text-right text-slate-800 font-medium">{{ row.value }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({
  title: { type: String, default: "" },
  data: { type: Array, default: () => [] },
});

const max = computed(() => Math.max(1, ...props.data.map(d => d.value || 0)));
function pct(v) { return Math.max(0, Math.min(100, ((v || 0) / max.value) * 100)); }
</script>
