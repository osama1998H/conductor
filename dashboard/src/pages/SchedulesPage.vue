<template>
  <div class="space-y-4">
    <div class="flex gap-2">
      <Input v-model="filters.q" placeholder="search name…" class="max-w-xs" />
      <Button variant="outline" @click="reload">Refresh</Button>
    </div>

    <Card class="p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Cron</TableHead>
            <TableHead>TZ</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead>Next run</TableHead>
            <TableHead>Last status</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in rows"
            :key="row.name"
            :class="['cursor-pointer', row.name === name ? 'bg-muted' : 'hover:bg-muted/50']"
          >
            <TableCell class="font-mono text-xs" @click="open(row.name)">{{ row.name }}</TableCell>
            <TableCell class="font-mono text-xs" @click="open(row.name)">
              <HoverCard :open-delay="200" :close-delay="100">
                <HoverCardTrigger as-child>
                  <span class="cursor-pointer underline-offset-4 hover:underline">{{ row.cron_expression }}</span>
                </HoverCardTrigger>
                <HoverCardContent side="top" align="start" class="w-auto max-w-sm text-sm">
                  {{ cronToEnglish(row.cron_expression) || "Unable to parse expression." }}
                </HoverCardContent>
              </HoverCard>
            </TableCell>
            <TableCell @click="open(row.name)">{{ row.timezone }}</TableCell>
            <TableCell>
              <Switch
                :model-value="!!row.enabled"
                :disabled="!isSysMgr"
                @update:model-value="onToggleEnabled(row)"
              />
            </TableCell>
            <TableCell class="text-2xs text-muted-foreground" @click="open(row.name)">{{ row.next_run_at }}</TableCell>
            <TableCell @click="open(row.name)">
              <StatusBadge v-if="row.last_status" :status="row.last_status" />
            </TableCell>
            <TableCell>
              <Button
                size="sm"
                :disabled="!isOperator"
                @click.stop="onRunNow(row.name)"
                title="Dispatches now; cron cadence is unaffected."
              >Run now</Button>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No schedules.</div>
    </Card>

    <Sheet :open="!!name" @update:open="onSheetOpenChange">
      <SheetContent side="right" class="w-[480px] sm:w-[640px] sm:max-w-[640px] overflow-y-auto">
        <template v-if="schedule">
          <SheetHeader>
            <SheetTitle class="font-mono text-base">{{ schedule.name }}</SheetTitle>
            <SheetDescription>
              <HoverCard :open-delay="200" :close-delay="100">
                <HoverCardTrigger as-child>
                  <code class="font-mono cursor-pointer underline-offset-4 hover:underline">{{ schedule.cron_expression }}</code>
                </HoverCardTrigger>
                <HoverCardContent side="bottom" align="start" class="w-auto max-w-sm text-sm">
                  {{ cronToEnglish(schedule.cron_expression) || "Unable to parse expression." }}
                </HoverCardContent>
              </HoverCard>
              · {{ schedule.timezone }}
            </SheetDescription>
          </SheetHeader>

          <div class="space-y-4 py-4">
            <section>
              <h4 class="text-sm font-medium mb-2">Last dispatch</h4>
              <p v-if="schedule.last_status" class="text-sm">
                <StatusBadge :status="schedule.last_status" /> at
                <span class="text-2xs text-muted-foreground">{{ schedule.last_run_at }}</span>
              </p>
              <p v-else class="text-sm text-muted-foreground">(never dispatched)</p>
            </section>

            <section v-if="schedule.last_job">
              <h4 class="text-sm font-medium mb-2">Last job</h4>
              <p class="text-sm">
                <RouterLink :to="`/jobs/${schedule.last_job}`" class="text-primary hover:underline">
                  {{ schedule.last_job }}
                </RouterLink>
                <StatusBadge v-if="lastJobStatus" :status="lastJobStatus" class="ml-2" />
              </p>
            </section>

            <section>
              <h4 class="text-sm font-medium mb-2">Next 10 fires</h4>
              <ul class="text-2xs text-muted-foreground space-y-0.5">
                <li v-for="f in nextFires" :key="f">{{ f }}</li>
              </ul>
            </section>

            <section>
              <h4 class="text-sm font-medium mb-2">Calendar</h4>
              <MiniCalendar :fires="nextFires" />
            </section>

            <section>
              <h4 class="text-sm font-medium mb-2">Recent runs</h4>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Job ID</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Enqueued</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="r in recentRuns" :key="r.job_id">
                    <TableCell>
                      <RouterLink :to="`/jobs/${r.job_id}`" class="font-mono text-primary hover:underline">
                        {{ r.job_id.slice(0, 8) }}…
                      </RouterLink>
                    </TableCell>
                    <TableCell><StatusBadge :status="r.status" /></TableCell>
                    <TableCell class="text-2xs text-muted-foreground">{{ r.enqueued_at }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </section>
          </div>
        </template>
        <div v-else class="p-6 text-center text-muted-foreground text-sm">Loading…</div>
      </SheetContent>
    </Sheet>
  </div>
</template>

<script setup>
import { ref, reactive, watch, toRefs } from "vue";
import { useRouter, RouterLink } from "vue-router";
import { api, getList } from "@/api";
import { useUserRoles } from "@/stores/useUserRoles";
import { confirm } from "@/stores/useConfirm";
import { toast } from "@/stores/useToast";
import StatusBadge from "@/components/StatusBadge.vue";
import MiniCalendar from "@/components/MiniCalendar.vue";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";
import {
  HoverCard, HoverCardContent, HoverCardTrigger,
} from "@/components/ui/hover-card";
import { cronToEnglish } from "@/lib/cron";

const props = defineProps({ name: String });
const router = useRouter();
const { name } = toRefs(props);

const filters = reactive({ q: "" });
const rows = ref([]);
const schedule = ref(null);
const nextFires = ref([]);
const recentRuns = ref([]);
const lastJobStatus = ref("");

const { isOperator, isSysMgr } = useUserRoles();

async function reload() {
  const f = {};
  if (filters.q) f.name = ["like", `%${filters.q}%`];
  rows.value = await getList("Conductor Schedule", {
    fields: ["name", "cron_expression", "timezone", "enabled", "next_run_at", "last_status", "last_run_at", "method", "last_job"],
    filters: f,
    order_by: "name asc",
    limit: 100,
  });
}

watch(filters, reload, { deep: true, immediate: true });

function open(n) { router.push({ path: `/schedules/${n}` }); }

async function loadDetail(n) {
  if (!n) { schedule.value = null; return; }
  const list = await getList("Conductor Schedule", {
    fields: ["name", "cron_expression", "timezone", "method", "queue", "enabled",
      "next_run_at", "last_status", "last_run_at", "last_job"],
    filters: { name: n },
    limit: 1,
  });
  schedule.value = list[0] || null;
  if (!schedule.value) return;

  const [fires, runs] = await Promise.all([
    api.getScheduleNextFires(n, 10),
    schedule.value.method ? getList("Conductor Job", {
      fields: ["job_id", "status", "enqueued_at"],
      filters: { method: schedule.value.method },
      order_by: "enqueued_at desc",
      limit: 20,
    }) : [],
  ]);
  nextFires.value = fires || [];
  recentRuns.value = runs || [];

  if (schedule.value.last_job) {
    try {
      const j = await api.getJob(schedule.value.last_job);
      lastJobStatus.value = j.status;
    } catch {
      lastJobStatus.value = "";
    }
  } else {
    lastJobStatus.value = "";
  }
}

watch(name, loadDetail, { immediate: true });

async function onRunNow(n) {
  if (!(await confirm(`Run schedule "${n}" now? This dispatches immediately and does not affect the cron cadence.`,
                       { title: "Run schedule now", confirmText: "Dispatch" }))) return;
  try {
    const newId = await api.scheduleRunNow(n);
    toast(`Dispatched as ${newId.slice(0, 8)}…`, "success");
    reload();
    if (name.value === n) loadDetail(n);
  } catch (e) {
    toast(`Run-now failed: ${e.message}`, "error");
  }
}

async function onToggleEnabled(row) {
  const next = !row.enabled;
  await api.scheduleSetEnabled(row.name, next);
  reload();
  if (name.value === row.name) loadDetail(row.name);
}

function onSheetOpenChange(open) {
  if (!open) router.push({ path: "/schedules" });
}
</script>
