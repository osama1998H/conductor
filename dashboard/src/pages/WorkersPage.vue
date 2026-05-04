<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="mb-3">
        <Button variant="outline" @click="reload">Refresh</Button>
      </div>
      <Card class="p-0 flex-1 overflow-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Worker</TableHead>
              <TableHead>Host</TableHead>
              <TableHead>PID</TableHead>
              <TableHead>Queues</TableHead>
              <TableHead>HB age</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in sortedRows"
              :key="row.name"
              :class="['cursor-pointer', row.name === worker_id ? 'bg-muted' : 'hover:bg-muted/50']"
              @click="open(row.name)"
            >
              <TableCell><StatusBadge :status="row.status" /></TableCell>
              <TableCell class="font-mono text-xs">{{ row.name }}</TableCell>
              <TableCell>{{ row.host }}</TableCell>
              <TableCell>{{ row.pid }}</TableCell>
              <TableCell class="font-mono text-xs">{{ parseQueues(row.queues) }}</TableCell>
              <TableCell>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <span class="text-xs text-muted-foreground">{{ heartbeatAge(row.last_heartbeat) }}</span>
                  </TooltipTrigger>
                  <TooltipContent>{{ row.last_heartbeat || "—" }}</TooltipContent>
                </Tooltip>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No workers registered.</div>
      </Card>
    </div>

    <div v-if="worker_id" class="flex-1 min-w-0 overflow-auto">
      <Card v-if="!detail">
        <CardContent class="p-6 text-center text-muted-foreground">Loading…</CardContent>
      </Card>
      <Card v-else>
        <CardHeader class="flex flex-row items-center gap-2 flex-wrap">
          <StatusBadge :status="detail.status" />
          <code class="font-mono text-sm">{{ detail.name }}</code>
          <span class="text-xs text-muted-foreground">· {{ detail.host }}:{{ detail.pid }}</span>
          <span v-if="detail.conductor_version" class="text-xs text-muted-foreground">· v{{ detail.conductor_version }}</span>
        </CardHeader>
        <CardContent class="space-y-4">
          <section>
            <h4 class="text-sm font-medium mb-2">Queues</h4>
            <p class="font-mono text-sm">{{ parseQueues(detail.queues) }}</p>
          </section>

          <section>
            <h4 class="text-sm font-medium mb-2">Heartbeat</h4>
            <p class="text-sm">
              Last beat at <span class="text-2xs text-muted-foreground">{{ detail.last_heartbeat }}</span>
              ({{ detail.heartbeat_age_seconds }}s ago)
            </p>
            <p class="text-sm">
              Started at <span class="text-2xs text-muted-foreground">{{ detail.started_at }}</span>
            </p>
          </section>

          <section v-if="detail.current_job">
            <h4 class="text-sm font-medium mb-2">Currently executing</h4>
            <p class="text-sm">
              <RouterLink :to="`/jobs/${detail.current_job}`" class="font-mono text-primary hover:underline">
                {{ detail.current_job }}
              </RouterLink>
              <StatusBadge v-if="currentJobStatus" :status="currentJobStatus" class="ml-2" />
            </p>
          </section>

          <section>
            <h4 class="text-sm font-medium mb-2">Recent jobs handled</h4>
            <Table v-if="detail.recent_jobs?.length">
              <TableHeader>
                <TableRow>
                  <TableHead>Job ID</TableHead>
                  <TableHead>Method</TableHead>
                  <TableHead>Queue</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Finished</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="r in detail.recent_jobs" :key="r.job_id">
                  <TableCell>
                    <RouterLink :to="`/jobs/${r.job_id}`" class="font-mono text-primary hover:underline">
                      {{ r.job_id.slice(0, 8) }}…
                    </RouterLink>
                  </TableCell>
                  <TableCell class="font-mono text-xs">{{ r.method }}</TableCell>
                  <TableCell>{{ r.queue }}</TableCell>
                  <TableCell><StatusBadge :status="r.status" /></TableCell>
                  <TableCell class="text-2xs text-muted-foreground">{{ r.finished_at }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
            <div v-else class="text-muted-foreground text-sm">No recent jobs.</div>
          </section>
        </CardContent>
      </Card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, toRefs } from "vue";
import { useRouter, RouterLink } from "vue-router";
import { api, getList } from "@/api";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const props = defineProps({ worker_id: String });
const router = useRouter();
const { worker_id } = toRefs(props);

const rows = ref([]);
const detail = ref(null);
const currentJobStatus = ref("");

function parseQueues(raw) {
  try {
    return (JSON.parse(raw || "[]")).join(", ");
  } catch {
    return String(raw || "");
  }
}

// `last_heartbeat` is stored UTC-naive (matches conductor.worker.now_naive).
// Frappe's API serializes it without a TZ suffix, e.g. "2026-05-04 11:39:30".
// JS Date constructor parses such strings as LOCAL time, adding the host's
// UTC offset as a phantom age. Normalize by appending 'Z' so it parses as UTC.
function parseUtcNaive(s) {
  if (!s) return null;
  const str = String(s);
  // Already has TZ info or is an epoch number.
  if (typeof s === "number" || /[zZ]|[+-]\d\d:?\d\d$/.test(str)) return new Date(s);
  return new Date(str.replace(" ", "T") + "Z");
}

function heartbeatAge(hb) {
  if (!hb) return "—";
  const d = parseUtcNaive(hb);
  if (!d) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

const STATUS_RANK = { ALIVE: 0, STALE: 1, GONE: 2 };

const sortedRows = computed(() => {
  return [...rows.value].sort((a, b) => {
    const aRank = STATUS_RANK[a.status] ?? 99;
    const bRank = STATUS_RANK[b.status] ?? 99;
    if (aRank !== bRank) return aRank - bRank;
    const av = parseUtcNaive(a.last_heartbeat);
    const bv = parseUtcNaive(b.last_heartbeat);
    return (bv ? bv.getTime() : 0) - (av ? av.getTime() : 0);
  });
});

async function reload() {
  rows.value = await getList("Conductor Worker", {
    fields: ["name", "host", "pid", "queues", "status", "last_heartbeat", "started_at"],
    order_by: "last_heartbeat desc",
    limit: 100,
  });
}

reload();

function open(id) {
  router.push({ path: `/workers/${id}` });
}

async function loadDetail(id) {
  if (!id) {
    detail.value = null;
    return;
  }
  detail.value = await api.getWorker(id);
  if (detail.value?.current_job) {
    try {
      const j = await api.getJob(detail.value.current_job);
      currentJobStatus.value = j.status;
    } catch {
      currentJobStatus.value = "";
    }
  } else {
    currentJobStatus.value = "";
  }
}

watch(worker_id, loadDetail, { immediate: true });
</script>
