// Safe Tauri bridge — degrades to no-ops in a plain browser (dev).
export function isTauri(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
}

async function win() {
  const mod = await import('@tauri-apps/api/window')
  return mod.getCurrentWindow()
}

export async function winMinimize() {
  try { (await win()).minimize() } catch { /* not in tauri */ }
}
export async function winToggleMaximize() {
  try { (await win()).toggleMaximize() } catch { /* not in tauri */ }
}
export async function winClose() {
  try { (await win()).close() } catch { /* not in tauri */ }
}
export async function winStartDrag() {
  try { (await win()).startDragging() } catch { /* not in tauri */ }
}
