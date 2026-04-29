<template>
  <div
    class="bg-white border border-slate-200 rounded-md px-5 py-4 cursor-pointer
           min-h-20 flex flex-col justify-between
           transition-colors duration-150 hover:border-primary"
    @click="$emit('click')"
  >
    <div class="text-3xl font-semibold text-slate-800">{{ value }}</div>
    <div class="text-xs text-slate-500 uppercase tracking-wider">{{ label }}</div>
  </div>
</template>

<script setup>
defineProps({
  value: { type: [Number, String], default: 0 },
  label: { type: String, required: true },
});
defineEmits(["click"]);
</script>
