<template>
  <AlertDialog :open="state.open" @update:open="onOpenChange">
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{{ state.title }}</AlertDialogTitle>
        <AlertDialogDescription>{{ state.message }}</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel @click="onCancel">{{ state.cancelText }}</AlertDialogCancel>
        <AlertDialogAction
          :class="state.danger ? 'bg-destructive text-white hover:bg-destructive/90' : ''"
          @click="onOk"
        >{{ state.confirmText }}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

<script setup>
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useConfirmState, _resolve } from "@/stores/useConfirm";

const state = useConfirmState();

function onOk() { _resolve(true); }
function onCancel() { _resolve(false); }

function onOpenChange(open) {
  if (!open) _resolve(false);
}
</script>
