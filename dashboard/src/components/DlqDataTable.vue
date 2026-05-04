<template>
  <div class="space-y-3">
    <div class="flex gap-2">
      <Select :model-value="filters.status || ALL_STATUSES" @update:model-value="(v) => emitFilter('status', v === ALL_STATUSES ? '' : (v ?? ''))">
        <SelectTrigger class="w-[200px]"><SelectValue placeholder="All statuses" /></SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL_STATUSES">All statuses</SelectItem>
          <SelectItem value="PENDING_REVIEW">Pending review</SelectItem>
          <SelectItem value="RETRIED">Retried</SelectItem>
          <SelectItem value="DISCARDED">Discarded</SelectItem>
        </SelectContent>
      </Select>
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
            :class="['cursor-pointer', row.original.name === selectedId ? 'bg-muted' : 'hover:bg-muted/50']"
          >
            <TableCell @click.stop>
              <Checkbox
                :model-value="selected.has(row.original.name)"
                @update:model-value="$emit('toggle-select', row.original.name)"
              />
            </TableCell>
            <TableCell
              v-for="cell in row.getVisibleCells().slice(1)"
              :key="cell.id"
              @click="$emit('select', row.original.name)"
            >
              <FlexRender :render="cell.column.columnDef.cell" :props="cell.getContext()" />
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
      <div v-if="!rows.length" class="p-6 text-center text-muted-foreground text-sm">No DLQ entries match.</div>
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
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const props = defineProps({
  rows: { type: Array, default: () => [] },
  filters: { type: Object, required: true },
  selected: { type: Set, required: true },
  selectedId: { type: String, default: "" },
});
const emit = defineEmits(["select", "toggle-select", "refresh", "filters-change"]);

const ALL_STATUSES = "__all__";

function emitFilter(key, value) {
  emit("filters-change", { ...props.filters, [key]: value });
}

const sorting = ref([{ id: "moved_at", desc: true }]);

const columns = [
  {
    id: "select",
    header: () => h("span", { class: "sr-only" }, "Select"),
    cell: () => null,
    enableSorting: false,
  },
  { accessorKey: "queue", header: "Queue" },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ row }) => h(StatusBadge, { status: row.getValue("status") }),
  },
  { accessorKey: "attempts", header: "Attempts" },
  {
    accessorKey: "last_error_type",
    header: "Last error",
    cell: ({ row }) => h("span", { class: "font-mono text-xs" }, row.getValue("last_error_type")),
  },
  {
    accessorKey: "moved_at",
    header: "Moved at",
    cell: ({ row }) =>
      h("span", { class: "text-2xs text-muted-foreground" }, row.getValue("moved_at")),
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
