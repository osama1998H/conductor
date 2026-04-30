<script setup>
import { ref, watch, onMounted } from 'vue';
import mermaid from 'mermaid';

const props = defineProps({
  snapshot: { type: String, required: true },
  steps: { type: Array, required: true },
});

const container = ref(null);
const STATUS_COLORS = {
  PENDING: '#e5e7eb',
  READY: '#bfdbfe',
  RUNNING: '#60a5fa',
  SUCCEEDED: '#86efac',
  FAILED: '#fca5a5',
  COMPENSATED: '#fdba74',
  SKIPPED: '#d1d5db',
};

function buildMermaid() {
  if (!props.snapshot) return '';
  let topo;
  try { topo = JSON.parse(props.snapshot); }
  catch { return 'flowchart TD\nerror[invalid snapshot]'; }
  const lines = ['flowchart TD'];
  const statusByStep = {};
  for (const s of props.steps) {
    if (!s.is_compensation) statusByStep[s.step_id] = s.status;
  }
  for (const step of topo.steps) {
    const status = statusByStep[step.name] || 'PENDING';
    lines.push(`  ${step.name}["${step.name}"]`);
    lines.push(`  style ${step.name} fill:${STATUS_COLORS[status] || '#e5e7eb'}`);
  }
  for (const step of topo.steps) {
    for (const dep of step.depends_on) {
      lines.push(`  ${dep} --> ${step.name}`);
    }
  }
  return lines.join('\n');
}

async function render() {
  if (!container.value) return;
  const code = buildMermaid();
  const { svg } = await mermaid.render('wf-dag', code);
  container.value.innerHTML = svg;
}

onMounted(() => {
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
  render();
});
watch(() => [props.snapshot, props.steps], render, { deep: true });
</script>

<template>
  <div ref="container" class="flex justify-center py-4" />
</template>
