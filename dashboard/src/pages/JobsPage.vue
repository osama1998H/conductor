<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <JobsDataTable
        :rows="rows"
        :filters="filters"
        :selected-id="job_id || ''"
        @select="open"
        @refresh="reload"
        @filters-change="onFiltersChange"
      />
    </div>

    <div v-if="job_id" class="flex-1 min-w-0 overflow-auto">
      <Card v-if="!detail">
        <CardContent class="p-6 text-center text-muted-foreground">Loading…</CardContent>
      </Card>
      <Card v-else>
        <CardHeader class="flex flex-row items-center gap-2 flex-wrap">
          <StatusBadge :status="detail.status" />
          <code class="font-mono text-sm">{{ detail.method }}</code>
          <span class="text-xs text-muted-foreground">· attempt {{ detail.attempt }}/{{ detail.max_attempts }}</span>
          <span class="text-xs text-muted-foreground">· queue {{ detail.queue }}</span>
        </CardHeader>
        <CardContent>
          <Tabs v-model="subtab" default-value="overview">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="runs">Runs ({{ detail.runs?.length || 0 }})</TabsTrigger>
              <TabsTrigger value="args">Args</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" class="space-y-4">
              <p v-if="detail.last_error_message" class="text-destructive text-sm">
                {{ detail.last_error_type }}: {{ detail.last_error_message }}
              </p>
              <details v-if="detail.last_traceback">
                <summary class="cursor-pointer text-sm">Traceback</summary>
                <pre class="font-mono text-2xs bg-muted p-2 rounded max-h-96 overflow-auto mt-2">{{ detail.last_traceback }}</pre>
              </details>
              <div class="flex gap-2">
                <Button :disabled="!canRetry" @click="onRetry">Retry</Button>
                <Button variant="destructive" :disabled="!canCancel" @click="onCancel">Cancel</Button>
              </div>
            </TabsContent>

            <TabsContent value="runs">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>#</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Started</TableHead>
                    <TableHead>Finished</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead>Error</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="r in (detail.runs || [])" :key="r.attempt_number">
                    <TableCell>{{ r.attempt_number }}</TableCell>
                    <TableCell><StatusBadge :status="r.status" /></TableCell>
                    <TableCell class="text-2xs text-muted-foreground">{{ r.started_at }}</TableCell>
                    <TableCell class="text-2xs text-muted-foreground">{{ r.finished_at }}</TableCell>
                    <TableCell>{{ r.duration_ms }}ms</TableCell>
                    <TableCell class="font-mono text-xs">{{ r.error_type }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </TabsContent>

            <TabsContent value="args" class="space-y-3">
              <h4 class="text-sm font-medium">args</h4>
              <JsonViewer :value="detail.args_decoded" />
              <h4 class="text-sm font-medium">kwargs</h4>
              <JsonViewer :value="detail.kwargs_decoded" />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList } from "@/api";
import { useDetailSubscription } from "@/stores/useDetailSubscription";
import { useUserRoles } from "@/stores/useUserRoles";
import { confirm } from "@/stores/useConfirm";
import { toast } from "@/stores/useToast";
import StatusBadge from "@/components/StatusBadge.vue";
import JsonViewer from "@/components/JsonViewer.vue";
import JobsDataTable from "@/components/JobsDataTable.vue";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const props = defineProps({ job_id: String });
const router = useRouter();
const { job_id } = toRefs(props);

const filters = reactive({ status: "", method: "", queue: "" });
const rows = ref([]);
const subtab = ref("overview");

async function reload() {
  const f = {};
  if (filters.status) f.status = filters.status;
  if (filters.queue) f.queue = filters.queue;
  if (filters.method) f.method = ["like", `%${filters.method}%`];
  rows.value = await getList("Conductor Job", {
    fields: ["job_id", "method", "queue", "status", "attempt", "enqueued_at", "last_error_message"],
    filters: f,
    order_by: "enqueued_at desc",
    limit: 50,
  });
}

watch(filters, reload, { deep: true, immediate: true });

function onFiltersChange(next) {
  Object.assign(filters, next);
}

function open(id) { router.push({ path: `/jobs/${id}` }); }

const { data: detail, refetch: refetchDetail } = useDetailSubscription(
  "Conductor Job",
  "conductor:job",
  job_id,
  () => api.getJob(job_id.value),
);

const { isOperator } = useUserRoles();

const canRetry = computed(() =>
  isOperator &&
  ["FAILED", "TIMED_OUT", "DLQ", "CANCELLED", "DISPATCH_FAILED"].includes(detail.value?.status)
);

const canCancel = computed(() =>
  isOperator &&
  ["QUEUED", "RUNNING", "SCHEDULED_RETRY"].includes(detail.value?.status)
);

async function onRetry() {
  if (!(await confirm(`Retry job ${job_id.value.slice(0, 8)}…?`,
                       { title: "Retry job", confirmText: "Retry" }))) return;
  try {
    const newId = await api.retryJob(job_id.value);
    toast(`Re-enqueued as ${newId.slice(0, 8)}…`, "success");
    reload();
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
  }
}

async function onCancel() {
  if (!(await confirm(`Cancel job ${job_id.value.slice(0, 8)}…?`,
                       { title: "Cancel job", confirmText: "Cancel job",
                         cancelText: "Keep running", danger: true }))) return;
  await api.cancelJob(job_id.value);
  toast("Job cancellation requested", "info");
  refetchDetail();
}
</script>
