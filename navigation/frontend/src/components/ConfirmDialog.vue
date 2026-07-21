<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  phrase: string
  message?: string
  busy?: boolean
  confirmLabel?: string
  fallbackFocusSelector?: string
}>(), { message: '', busy: false, confirmLabel: '确认继续', fallbackFocusSelector: '' })
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const typed = ref('')
const input = ref<HTMLInputElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
let focusOrigin: HTMLElement | null = null
let focusOriginTestId: string | null = null
let appRoot: HTMLElement | null = null
let appWasInert = false

function focusableElements(): HTMLElement[] {
  return dialog.value
    ? Array.from(dialog.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ))
    : []
}

function handleDocumentKeydown(event: KeyboardEvent): void {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    cancel()
    return
  }
  if (event.key !== 'Tab') return
  const focusable = focusableElements()
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && (document.activeElement === first || !dialog.value?.contains(document.activeElement))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (document.activeElement === last || !dialog.value?.contains(document.activeElement))) {
    event.preventDefault()
    first.focus()
  }
}

function deactivateModal(): void {
  document.removeEventListener('keydown', handleDocumentKeydown)
  if (appRoot && !appWasInert) appRoot.removeAttribute('inert')
  appRoot = null
  const origin = focusOrigin
  const originTestId = focusOriginTestId
  focusOrigin = null
  focusOriginTestId = null
  void nextTick(() => {
    const replacement = originTestId
      ? Array.from(document.querySelectorAll<HTMLElement>('[data-test]'))
        .find((element) => element.dataset.test === originTestId)
      : null
    const fallback = props.fallbackFocusSelector
      ? document.querySelector<HTMLElement>(props.fallbackFocusSelector)
      : null
    const target = origin?.isConnected ? origin : (replacement ?? fallback)
    target?.focus()
  })
}

watch(() => props.open, async (open) => {
  typed.value = ''
  if (open) {
    focusOrigin = document.activeElement instanceof HTMLElement ? document.activeElement : null
    focusOriginTestId = focusOrigin?.dataset.test ?? null
    appRoot = document.getElementById('app')
    appWasInert = appRoot?.hasAttribute('inert') ?? false
    appRoot?.setAttribute('inert', '')
    document.addEventListener('keydown', handleDocumentKeydown)
    await nextTick()
    input.value?.focus()
  } else if (focusOrigin || appRoot) {
    deactivateModal()
  }
}, { immediate: true })

watch(() => props.phrase, () => {
  typed.value = ''
})

function cancel(): void {
  if (!props.busy) emit('cancel')
}

onBeforeUnmount(deactivateModal)
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="dialog-backdrop" @click.self="cancel">
      <section ref="dialog" class="confirm-dialog" role="dialog" aria-modal="true" :aria-labelledby="`confirm-title-${phrase}`">
        <p class="eyebrow">DESTRUCTIVE ACTION</p>
        <h2 :id="`confirm-title-${phrase}`">{{ title }}</h2>
        <p v-if="message">{{ message }}</p>
        <p>请输入 <strong>{{ phrase }}</strong> 以确认。</p>
        <label>
          <span class="sr-only">确认文字</span>
          <input ref="input" v-model="typed" data-test="confirmation-input" autocomplete="off" :placeholder="phrase" />
        </label>
        <div class="dialog-actions">
          <button type="button" class="ghost-button" :disabled="busy" @click="cancel">取消</button>
          <button
            data-test="confirm-destructive"
            type="button"
            class="danger-button"
            :disabled="typed !== phrase || busy"
            @click="emit('confirm')"
          >{{ busy ? '处理中…' : confirmLabel }}</button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
