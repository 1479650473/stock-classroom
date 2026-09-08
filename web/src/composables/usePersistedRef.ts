// localStorage 持久化的 ref：让页面记住用户上次的选择，下次打开自动恢复。
//
// 用法：
//   const days = usePersistedRef('market.days', '250')
//   const form = usePersistedRef('trade.form', { code: '', qty: 100 })
//
// 说明：桌面单用户场景用 localStorage 足够，且无网络往返；
// 主题/字体等需要与后端 settings.json 共享的配置仍走 app store。
import { ref, watch, type Ref } from 'vue'

const PREFIX = 'sc_'

function read<T>(key: string, def: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (raw === null) return def
    const parsed = JSON.parse(raw) as T
    // 对象默认值与历史数据合并，避免新增字段变 undefined
    if (
      parsed &&
      def &&
      typeof parsed === 'object' &&
      typeof def === 'object' &&
      !Array.isArray(parsed) &&
      !Array.isArray(def)
    ) {
      return { ...(def as object), ...(parsed as object) } as T
    }
    return parsed
  } catch {
    return def
  }
}

export function usePersistedRef<T>(key: string, def: T): Ref<T> {
  const state = ref(read(key, def)) as Ref<T>
  watch(
    state,
    (v) => {
      try {
        localStorage.setItem(PREFIX + key, JSON.stringify(v))
      } catch {
        /* 配额满 / 隐私模式：静默降级为不持久化 */
      }
    },
    { deep: true },
  )
  return state
}

/** 读取一个已持久化的值（不建立响应式绑定） */
export function readPersisted<T>(key: string, def: T): T {
  return read(key, def)
}

/** 清除指定前缀的持久化数据 */
export function clearPersisted(keys: string[]) {
  for (const k of keys) {
    try {
      localStorage.removeItem(PREFIX + k)
    } catch {
      /* ignore */
    }
  }
}
