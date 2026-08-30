import { defineStore } from 'pinia'

export interface Toast {
  id: number
  kind: 'success' | 'error' | 'info'
  text: string
}

let _id = 0

export const useToastStore = defineStore('toast', {
  state: () => ({ toasts: [] as Toast[] }),
  actions: {
    push(kind: Toast['kind'], text: string, timeout = 3000) {
      const id = ++_id
      this.toasts.push({ id, kind, text })
      setTimeout(() => this.dismiss(id), timeout)
    },
    success(t: string) { this.push('success', t) },
    error(t: string) { this.push('error', t, 4500) },
    info(t: string) { this.push('info', t) },
    dismiss(id: number) {
      this.toasts = this.toasts.filter((t) => t.id !== id)
    },
  },
})
