<template>
  <div class="mini-calendar">
    <div class="day-of-week" v-for="(d, i) in DOW" :key="i">{{ d }}</div>
    <div v-for="cell in cells" :key="cell.iso"
      :class="['day', { 'has-fires': cell.fires > 0, 'today': cell.iso === todayISO }]">
      <span class="num">{{ cell.day }}</span>
      <span v-if="cell.fires > 0" class="dot" :title="`${cell.fires} fires`"></span>
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

<style scoped>
.mini-calendar {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  max-width: 320px;
}

.day-of-week {
  text-align: center;
  font-size: 10px;
  color: #94a3b8;
  padding: 4px;
}

.day {
  aspect-ratio: 1;
  padding: 4px;
  background: #f8fafc;
  border-radius: 3px;
  position: relative;
}

.day.today {
  outline: 1px solid #2563eb;
}

.day.has-fires {
  background: #dbeafe;
}

.day .num {
  font-size: 11px;
  color: #475569;
}

.day .dot {
  position: absolute;
  bottom: 4px;
  right: 4px;
  width: 6px;
  height: 6px;
  background: #2563eb;
  border-radius: 50%;
}
</style>
