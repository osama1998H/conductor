<template>
  <div class="space-y-6">
    <section class="space-y-3">
      <h2 class="text-xl font-semibold">Workflow definitions</h2>
      <Card class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>Active</TableHead>
              <TableHead>24h</TableHead>
              <TableHead>Last bump</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="w in workflows"
              :key="w.workflow_name"
              :class="['cursor-pointer', selectedWorkflow === w.workflow_name ? 'bg-muted' : 'hover:bg-muted/50']"
              @click="selectWorkflow(w.workflow_name)"
            >
              <TableCell class="font-mono text-xs">{{ w.workflow_name }}</TableCell>
              <TableCell>v{{ w.version }}</TableCell>
              <TableCell>{{ w.active_runs }}</TableCell>
              <TableCell>{{ w.recent_runs_24h }}</TableCell>
              <TableCell class="text-2xs text-muted-foreground">{{ w.last_version_bumped_at || "—" }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!workflows.length" class="p-6 text-center text-muted-foreground text-sm">
          No workflows registered.
        </div>
      </Card>
    </section>

    <section class="space-y-3">
      <h3 class="text-lg font-semibold">
        {{ selectedWorkflow ? `Runs of ${selectedWorkflow}` : "Recent runs (all workflows)" }}
      </h3>
      <Card class="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Run ID</TableHead>
              <TableHead>Workflow</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>Finished</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="r in recentRuns" :key="r.name" class="hover:bg-muted/50">
              <TableCell>
                <RouterLink :to="`/workflows/runs/${r.name}`" class="font-mono text-primary hover:underline">
                  {{ r.name }}
                </RouterLink>
              </TableCell>
              <TableCell class="font-mono text-xs">{{ r.workflow }} (v{{ r.definition_version }})</TableCell>
              <TableCell><StatusBadge :status="r.status" /></TableCell>
              <TableCell class="text-2xs text-muted-foreground">{{ r.started_at || "—" }}</TableCell>
              <TableCell class="text-2xs text-muted-foreground">{{ r.finished_at || "—" }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!recentRuns.length" class="p-6 text-center text-muted-foreground text-sm">No runs yet.</div>
      </Card>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { RouterLink } from "vue-router";
import { listWorkflows, listWorkflowRuns } from "@/api";
import { useAutoPolling } from "@/stores/useDashboardState";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const workflows = ref([]);
const recentRuns = ref([]);
const selectedWorkflow = ref(null);

async function refresh() {
  workflows.value = await listWorkflows();
  recentRuns.value = await listWorkflowRuns({
    workflow: selectedWorkflow.value,
    limit: 50,
  });
}

useAutoPolling();
onMounted(refresh);

function selectWorkflow(name) {
  selectedWorkflow.value = name;
  refresh();
}
</script>
