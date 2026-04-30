<template>
  <div class="space-y-3">
    <div class="flex gap-2">
      <Select :model-value="filters.status || ALL_STATUSES" @update:model-value="(v) => emitFilter('status', v === ALL_STATUSES ? '' : (v ?? ''))">
        <SelectTrigger class="w-[180px]"><SelectValue placeholder="All statuses" /></SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL_STATUSES">All statuses</SelectItem>
          <SelectItem v-for="s in STATUSES" :key="s" :value="s">{{ s }}</SelectItem>
        </SelectContent>
      </Select>
      <Input
        :model-value="filters.method"
        placeholder="method contains…"
        class="max-w-xs"
        @update:model-value="(v) => emitFilter('method', v)"
      />
      <Input
        :model-value="filters.queue"
        placeholder="queue"
        class="max-w-[160px]"
        @update:model-value="(v) => emitFilter('queue', v)"
      />
      <Button variant="outline" @click="$emit('refresh')">Refresh</Button>
    </div>

    <Card class="p-0">
      <Table>
        <TableHeader>
          <TableRow v-for="headerGroup in table.getHeaderGroups()" :key="headerGroup.id">
            <TableHead
              v-for="header in headerGroup.headers"
              :key="header.id"
              :class="header.column.getCanSort() ? 'cursor-pointer select-none' : ''"
              @click="header.column.getToggleSortingHandler()?.($event)"
            >
              <FlexRender :render="header.column.columnDef.header" :props="header.getContext()" />
              <span v-if="header.column.getIsSorted() === 'asc'" class="ml-1">↑</span>
              <span v-else-if="header.column.getIsSorted() === 'desc'" class="ml-1">↓</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in table.getRowModel().rows"
            :key="row.id"
            :class="['cursor-pointer', row.original.job_id === selectedId ? 'bg-muted' : 'hover:bg-muted/50']"
            @click="$emit('select', row.original.job_id)"
          >
            <TableCell v-for="cell in row.getVisibleCells()" :key="cell.id">
              <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No jobs match.</div>
      <div v-else class="flex items-center justify-end gap-2 p-3 border-t">
        <span class="text-xs text-muted-foreground">
          Page {{ table.getState().pagination.pageIndex + 1 }} of {{ table.getPageCount() || 1 }}
          · {{ table.getRowModel().rows.length }} of {{ rows.length }} rows
        </span>
        <Button size="sm" variant="outline" :disabled="!table.getCanPreviousPage()" @click="table.previousPage()">
          Previous
        </Button>
        <Button size="sm" variant="outline" :disabled="!table.getCanNextPage()" @click="table.nextPage()">
          Next
        </Button>
      </div>
    </Card>
  </div>
</template>

<script setup>
import { ref, h } from "vue";
import {
  FlexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useVueTable,
} from "@tanstack/vue-table";
import StatusBadge from "@/components/StatusBadge.vue";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

const props = defineProps({
  rows: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  selectedId: { type: String, default: "" },
});
const emit = defineEmits(["select", "refresh", "filters-change"]);

const ALL_STATUSES = "__all__";
const STATUSES = [
  "QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DLQ",
  "TIMED_OUT", "SCHEDULED_RETRY", "CANCELLED", "DISPATCH_FAILED",
];

function emitFilter(key, value) {
  emit("filters-change", { ...props.filters, [key]: value });
}

const sorting = ref([{ id: "enqueued_at", desc: true }]);

const columns = [
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => h(StatusBadge, { status: row.getValue("status") }),
  },
  {
    accessorKey: "method",
    header: "Method",
    cell: ({ row }) => h("span", { class: "font-mono text-xs" }, row.getValue("method")),
  },
  { accessorKey: "queue", header: "Queue" },
  { accessorKey: "attempt", header: "Attempt" },
  {
    accessorKey: "enqueued_at",
    header: "Enqueued",
    cell: ({ row }) =>
      h("span", { class: "text-2xs text-muted-foreground" }, row.getValue("enqueued_at")),
  },
];

const table = useVueTable({
  get data() { return props.rows; },
  columns,
  state: {
    get sorting() { return sorting.value; },
  },
  onSortingChange: (updater) => {
    sorting.value = typeof updater === "function" ? updater(sorting.value) : updater;
  },
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
  getPaginationRowModel: getPaginationRowModel(),
  initialState: { pagination: { pageSize: 25 } },
});
</script>
