<template>
  <div class="chart">
    <div class="title">{{ title }}</div>
    <div v-if="!data.length" class="empty">No data</div>
    <div v-else>
      <div v-for="row in data" :key="row.label" class="row">
        <div class="row-label">{{ row.label }}</div>
        <div class="bar-track">
          <div class="bar-fill" :style="{ width: pct(row.value) + '%' }"></div>
        </div>
        <div class="row-value">{{ row.value }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({
  title: { type: String, default: "" },
  data: { type: Array, default: () => [] },  // [{ label, value }]
});

const max = computed(() => Math.max(1, ...props.data.map(d => d.value || 0)));
function pct(v) { return Math.max(0, Math.min(100, ((v || 0) / max.value) * 100)); }
</script>

<style scoped>
.chart {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 16px;
}

.title {
  font-size: 13px;
  font-weight: 500;
  color: #475569;
  margin-bottom: 12px;
}

.row {
  display: grid;
  grid-template-columns: 100px 1fr 50px;
  gap: 12px;
  align-items: center;
  padding: 4px 0;
  font-size: 12px;
}

.row-label {
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bar-track {
  background: #f1f5f9;
  height: 14px;
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  background: #2563eb;
  height: 100%;
  transition: width 0.3s;
}

.row-value {
  text-align: right;
  color: #1e293b;
  font-weight: 500;
}

.empty {
  color: #94a3b8;
  padding: 16px;
  text-align: center;
  font-size: 12px;
}
</style>
