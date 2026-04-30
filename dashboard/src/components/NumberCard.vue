<template>
  <Card class="cursor-pointer transition-colors hover:border-primary" @click="$emit('click')">
    <CardHeader class="pb-2">
      <CardDescription class="text-xs uppercase tracking-wider">{{ label }}</CardDescription>
    </CardHeader>
    <CardContent>
      <div class="text-3xl font-semibold">{{ value }}</div>
    </CardContent>
  </Card>
</template>

<script setup>
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

defineProps({
  value: { type: [Number, String], default: 0 },
  label: { type: String, required: true },
});
defineEmits(["click"]);
</script>
