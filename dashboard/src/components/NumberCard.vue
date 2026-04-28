<template>
  <div class="card" @click="$emit('click')">
    <div class="value">{{ value }}</div>
    <div class="label">{{ label }}</div>
  </div>
</template>

<script setup>
defineProps({
  value: { type: [Number, String], default: 0 },
  label: { type: String, required: true },
});
defineEmits(["click"]);
</script>

<style scoped>
.card {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 16px 20px;
  cursor: pointer;
  transition: border-color 0.15s;
  min-height: 80px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.card:hover {
  border-color: #2563eb;
}

.value {
  font-size: 28px;
  font-weight: 600;
  color: #1e293b;
}

.label {
  font-size: 12px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
</style>
