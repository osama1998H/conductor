<template>
  <Dialog :open="true" @update:open="(o) => !o && $emit('cancel')">
    <DialogContent class="sm:max-w-[640px] max-h-[80vh] overflow-auto">
      <DialogHeader>
        <DialogTitle>Edit &amp; retry — {{ entryName }}</DialogTitle>
        <DialogDescription class="text-xs">
          JSON-validated on save. Edited payload must remain JSON-native.
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-3">
        <div>
          <Label>args (JSON array)</Label>
          <Textarea v-model="argsText" rows="5" class="font-mono text-xs" />
        </div>
        <div>
          <Label>kwargs (JSON object)</Label>
          <Textarea v-model="kwargsText" rows="10" class="font-mono text-xs" />
        </div>
        <p v-if="error" class="text-destructive text-sm">{{ error }}</p>
      </div>

      <DialogFooter>
        <Button variant="outline" :disabled="saving" @click="$emit('cancel')">Cancel</Button>
        <Button :disabled="saving" @click="onSave">{{ saving ? "Saving…" : "Save & retry" }}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { ref } from "vue";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const props = defineProps({
  entryName: { type: String, required: true },
  initialArgs: { type: Array, default: () => [] },
  initialKwargs: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["cancel", "saved"]);

const argsText = ref(JSON.stringify(props.initialArgs, null, 2));
const kwargsText = ref(JSON.stringify(props.initialKwargs, null, 2));
const error = ref("");
const saving = ref(false);

async function onSave() {
  error.value = "";
  let parsedArgs, parsedKwargs;
  try { parsedArgs = JSON.parse(argsText.value); } catch { error.value = "args is not valid JSON"; return; }
  try { parsedKwargs = JSON.parse(kwargsText.value); } catch { error.value = "kwargs is not valid JSON"; return; }

  saving.value = true;
  try {
    const newId = await api.dlqEditAndRetry(
      props.entryName,
      JSON.stringify(parsedArgs),
      JSON.stringify(parsedKwargs),
    );
    emit("saved", newId);
  } catch (e) {
    error.value = e.message || "Save failed";
  } finally {
    saving.value = false;
  }
}
</script>
