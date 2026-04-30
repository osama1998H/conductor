<template>
  <div v-if="data && data.run" class="space-y-4">
    <Card>
      <CardHeader class="flex flex-row items-center gap-3 flex-wrap">
        <Button variant="outline" size="sm" @click="router.back()">&laquo; Back</Button>
        <CardTitle class="font-mono text-sm">{{ data.run.name }}</CardTitle>
        <StatusBadge :status="data.run.status" />
        <Button v-if="canCancel" variant="destructive" size="sm" @click="cancel">Cancel run</Button>
      </CardHeader>
      <CardContent class="text-sm space-y-1">
        <div>
          <span class="text-muted-foreground">Workflow:</span>
          <code class="font-mono ml-1">{{ data.run.workflow }}</code>
          <span class="text-muted-foreground ml-1">(v{{ data.run.definition_version }})</span>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>DAG</CardTitle></CardHeader>
      <CardContent>
        <MermaidDag :snapshot="data.snapshot" :steps="data.steps" />
      </CardContent>
    </Card>

    <Card class="p-0">
      <CardHeader><CardTitle>Step runs</CardTitle></CardHeader>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Step</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Started</TableHead>
            <TableHead>Finished</TableHead>
            <TableHead>Job</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="s in data.steps" :key="s.name">
            <TableCell class="font-mono text-xs">{{ s.step_id }}</TableCell>
            <TableCell>{{ s.is_compensation ? "compensation" : "forward" }}</TableCell>
            <TableCell><StatusBadge :status="s.status" /></TableCell>
            <TableCell class="text-2xs text-muted-foreground">{{ s.started_at || "—" }}</TableCell>
            <TableCell class="text-2xs text-muted-foreground">{{ s.finished_at || "—" }}</TableCell>
            <TableCell>
              <RouterLink v-if="s.job" :to="`/jobs/${s.job}`" class="font-mono text-primary hover:underline">
                {{ s.job }}
              </RouterLink>
              <span v-else class="text-muted-foreground">—</span>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Card>

    <Card v-if="data.run.last_error">
      <CardHeader><CardTitle>Last error</CardTitle></CardHeader>
      <CardContent>
        <pre class="bg-muted p-3 rounded font-mono text-2xs overflow-x-auto">{{ data.run.last_error }}</pre>
      </CardContent>
    </Card>
  </div>
  <div v-else class="p-6 text-center text-muted-foreground">Loading…</div>
</template>

<script setup>
import { useRouter, RouterLink } from "vue-router";
import { useUserRoles } from "@/stores/useUserRoles";
import { computed, toRefs } from "vue";
import { getWorkflowRun, cancelWorkflowRun } from "@/api";
import { useDetailSubscription } from "@/stores/useDetailSubscription";
import MermaidDag from "@/components/MermaidDag.vue";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const props = defineProps({ run_id: String });
const router = useRouter();
const { run_id } = toRefs(props);

const { data, refetch: refetchData } = useDetailSubscription(
  "Conductor Workflow Run",
  "conductor:workflow_run",
  run_id,
  () => getWorkflowRun(run_id.value),
);

const { isOperator, isSysMgr } = useUserRoles();
const canCancel = computed(() =>
  data.value && data.value.run && data.value.run.status === "RUNNING" && (isOperator.value || isSysMgr.value)
);

async function cancel() {
  await cancelWorkflowRun(run_id.value);
  await refetchData();
}
</script>
