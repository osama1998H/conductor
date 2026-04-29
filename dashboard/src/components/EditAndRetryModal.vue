<template>
  <div
    class="fixed inset-0 bg-black/40 flex items-center justify-center z-[100]"
    @click.self="$emit('cancel')"
  >
    <div class="bg-white rounded-md p-5 min-w-[480px] max-w-[720px] max-h-[80vh] overflow-auto">
      <h3 class="mt-0">Edit &amp; retry — {{ entryName }}</h3>
      <p class="text-xs text-slate-500 mb-4">JSON-validated on save. Edited payload must remain JSON-native.</p>

      <label class="block text-xs font-medium mt-2 mb-1">args (JSON array)</label>
      <textarea
        v-model="argsText"
        rows="5"
        class="w-full font-mono text-xs p-2 border border-slate-300 rounded"
      ></textarea>
      <label class="block text-xs font-medium mt-2 mb-1">kwargs (JSON object)</label>
      <textarea
        v-model="kwargsText"
        rows="10"
        class="w-full font-mono text-xs p-2 border border-slate-300 rounded"
      ></textarea>

      <div v-if="error" class="text-red-800 my-2">{{ error }}</div>

      <div class="flex justify-end gap-2 mt-4">
        <button
          class="px-3.5 py-1.5 border border-slate-300 bg-white rounded cursor-pointer
                 disabled:opacity-60 disabled:cursor-not-allowed"
          @click="$emit('cancel')"
        >Cancel</button>
        <button
          class="px-3.5 py-1.5 bg-primary text-white border border-primary rounded cursor-pointer
                 disabled:opacity-60 disabled:cursor-not-allowed"
          @click="onSave"
          :disabled="saving"
        >{{ saving ? "Saving…" : "Save & retry" }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { api } from "../api";

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
    const newId = await api.dlqEditAndRetry(props.entryName, JSON.stringify(parsedArgs), JSON.stringify(parsedKwargs));
    emit("saved", newId);
  } catch (e) {
    error.value = e.message || "Save failed";
  } finally {
    saving.value = false;
  }
}
</script>
