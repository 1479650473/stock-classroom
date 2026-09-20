// Safe Tauri bridge — degrades to no-ops in a plain browser (dev).
export function isTauri(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
}

async function win() {
  const mod = await import('@tauri-apps/api/window')
  return mod.getCurrentWindow()
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T | null> {
  if (!isTauri()) return null
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    return (await invoke(cmd, args)) as T
  } catch {
    return null
  }
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

// ───────────────────── 桌面外壳能力（托盘/闪屏/通知/自启） ─────────────────────

export interface DesktopPrefs {
  /** 点关闭按钮时最小化到托盘（默认 true，像微信） */
  close_to_tray: boolean
  /** 任务完成/失败时弹系统通知（默认 true） */
  system_notify: boolean
}

/** 告诉外壳：前端已就绪 → 关闪屏、显示主窗口 */
export async function appReady(): Promise<void> {
  await call('app_ready')
}

export async function getDesktopPrefs(): Promise<DesktopPrefs | null> {
  return call<DesktopPrefs>('get_desktop_prefs')
}

export async function setDesktopPrefs(prefs: DesktopPrefs): Promise<DesktopPrefs | null> {
  return call<DesktopPrefs>('set_desktop_prefs', { prefs })
}

export async function getAutostart(): Promise<boolean> {
  return (await call<boolean>('get_autostart')) ?? false
}

export async function setAutostart(enabled: boolean): Promise<boolean> {
  return (await call<boolean>('set_autostart', { enabled })) ?? false
}

/** 系统通知（Windows 通知中心；非 Tauri 环境静默忽略） */
export async function systemNotify(title: string, body: string): Promise<void> {
  await call('system_notify', { title, body })
}

export async function hideToTray(): Promise<void> {
  await call('hide_to_tray')
}

export async function quitApp(): Promise<void> {
  await call('quit_app')
}
