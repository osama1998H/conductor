<template>
  <div class="modal-backdrop" @click.self="$emit('cancel')">
    <div class="modal">
      <h3>Edit &amp; retry — {{ entryName }}</h3>
      <p class="hint">JSON-validated on save. Edited payload must remain JSON-native.</p>

      <label>args (JSON array)</label>
      <textarea v-model="argsText" rows="5"></textarea>
      <label>kwargs (JSON object)</label>
      <textarea v-model="kwargsText" rows="10"></textarea>

      <div v-if="error" class="error">{{ error }}</div>

      <div class="actions">
        <button @click="$emit('cancel')">Cancel</button>
        <button class="primary" @click="onSave" :disabled="saving">{{ saving ? "Saving…" : "Save & retry" }}</button>
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

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  background: white;
  border-radius: 6px;
  padding: 20px;
  min-width: 480px;
  max-width: 720px;
  max-height: 80vh;
  overflow: auto;
}

.modal h3 {
  margin-top: 0;
}

.hint {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 16px;
}

label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  margin: 8px 0 4px;
}

textarea {
  width: 100%;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  padding: 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
}

.error {
  color: #991b1b;
  margin: 8px 0;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.actions button {
  padding: 6px 14px;
  border: 1px solid #ccc;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.actions button.primary {
  background: #2563eb;
  color: white;
  border-color: #2563eb;
}

.actions button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
