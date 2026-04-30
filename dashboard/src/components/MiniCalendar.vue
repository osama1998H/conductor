<template>
  <div class="grid grid-cols-7 gap-0.5 max-w-80">
    <div v-for="(d, i) in DOW" :key="i" class="text-center text-[10px] text-muted-foreground p-1">{{ d }}</div>
    <div
      v-for="cell in cells"
      :key="cell.iso"
      :class="[
        'aspect-square p-1 rounded-sm relative bg-muted',
        cell.fires > 0 && 'bg-primary/15',
        cell.iso === todayISO && 'outline outline-1 outline-primary',
      ]"
    >
      <span class="text-2xs text-foreground">{{ cell.day }}</span>
      <span
        v-if="cell.fires > 0"
        class="absolute bottom-1 right-1 w-1.5 h-1.5 bg-primary rounded-full"
        :title="`${cell.fires} fires`"
      ></span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({ fires: { type: Array, default: () => [] } });

const DOW = ["S", "M", "T", "W", "T", "F", "S"];
const todayISO = new Date().toISOString().slice(0, 10);

const cells = computed(() => {
  const out = [];
  const today = new Date();
  const start = new Date(today);
  start.setDate(today.getDate() - today.getDay());
  for (let i = 0; i < 28; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const iso = d.toISOString().slice(0, 10);
    const fires = props.fires.filter(f => String(f).startsWith(iso)).length;
    out.push({ iso, day: d.getDate(), fires });
  }
  return out;
});
</script>
