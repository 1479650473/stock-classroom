<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import EmptyGuide from './EmptyGuide.vue'
import LoadingBlock from './LoadingBlock.vue'
import Icon from '@/components/Icon.vue'

export interface DataColumn {
  key: string
  title: string
  align?: 'left' | 'right' | 'center'
  width?: string
  sortable?: boolean
  /** 简单文本格式化；复杂内容用 #cell-{key} 插槽 */
  format?: (row: Record<string, unknown>) => string
  /** 单元格附加 class（固定或按行计算） */
  cellClass?: string | ((row: Record<string, unknown>) => string)
}

/**
 * 统一数据表格：列定义 + 排序 + 分页 + 空状态 + 行操作。
 * 所有列表页必须使用它，保证全站表格视觉与交互一致。
 */
const props = withDefaults(
  defineProps<{
    columns: DataColumn[]
    rows: Record<string, unknown>[]
    rowKey?: string
    loading?: boolean
    emptyTitle?: string
    emptyDesc?: string
    /** >0 时启用前端分页 */
    pageSize?: number
    compact?: boolean
    /** 行操作列 hover 才显示（默认 true） */
    hoverActions?: boolean
    /** 允许拖拽调整列宽（默认 true） */
    resizable?: boolean
    /** 允许显示/隐藏列（默认 true，列数 ≥ 4 时出现按钮） */
    columnToggle?: boolean
    /** 记忆键：同一张表用它持久化列宽/列显隐（不传则不持久化） */
    storageKey?: string
  }>(),
  {
    rowKey: 'id',
    loading: false,
    emptyTitle: '暂无数据',
    pageSize: 0,
    compact: false,
    hoverActions: true,
    resizable: true,
    columnToggle: true,
    storageKey: '',
  },
)

const emit = defineEmits<{ rowClick: [row: Record<string, unknown>] }>()

const sortKey = ref('')
const sortDir = ref<'asc' | 'desc'>('asc')
const page = ref(1)

/** 列宽（px）与隐藏列：按 storageKey 记忆到 localStorage */
const widths = ref<Record<string, number>>({})
const hidden = ref<string[]>([])
const resizing = ref('')
const showColPicker = ref(false)
const LS_PREFIX = 'sc_dt_'

function loadPrefs() {
  widths.value = {}
  hidden.value = []
  if (!props.storageKey) return
  try {
    const raw = localStorage.getItem(LS_PREFIX + props.storageKey)
    if (raw) {
      const p = JSON.parse(raw) as { w?: Record<string, number>; h?: string[] }
      widths.value = p.w || {}
      hidden.value = (p.h || []).filter((k) => props.columns.some((c) => c.key === k))
    }
  } catch {
    /* 数据损坏时忽略 */
  }
}

function savePrefs() {
  if (!props.storageKey) return
  try {
    localStorage.setItem(LS_PREFIX + props.storageKey, JSON.stringify({ w: widths.value, h: hidden.value }))
  } catch {
    /* 隐私模式等场景静默失败 */
  }
}

const visibleColumns = computed(() => props.columns.filter((c) => !hidden.value.includes(c.key)))

function colStyle(c: { key: string; width?: string; align?: string }) {
  const w = widths.value[c.key]
  return { width: w ? `${w}px` : c.width, textAlign: (c.align || 'left') as 'left' | 'right' | 'center' }
}

function toggleColumn(key: string) {
  const i = hidden.value.indexOf(key)
  if (i >= 0) hidden.value.splice(i, 1)
  else if (visibleColumns.value.length > 1) hidden.value.push(key)
  savePrefs()
}

/** 拖拽调列宽：mousedown 后跟随鼠标，最小 56px */
function startResize(e: MouseEvent, key: string) {
  if (!props.resizable) return
  e.preventDefault()
  e.stopPropagation()
  const th = (e.target as HTMLElement).closest('th') as HTMLElement | null
  const startX = e.clientX
  const startW = th?.offsetWidth ?? 120
  resizing.value = key
  const move = (ev: MouseEvent) => {
    const w = Math.max(56, Math.round(startW + (ev.clientX - startX)))
    widths.value = { ...widths.value, [key]: w }
  }
  const up = () => {
    resizing.value = ''
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', up)
    savePrefs()
  }
  document.addEventListener('mousemove', move)
  document.addEventListener('mouseup', up)
}

function resetColumns() {
  widths.value = {}
  hidden.value = []
  savePrefs()
}

watch(() => props.columns, loadPrefs)
watch(() => props.storageKey, loadPrefs)
onMounted(loadPrefs)

function toggleSort(key: string) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
  page.value = 1
}

const sortedRows = computed(() => {
  if (!sortKey.value) return props.rows
  const k = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return [...props.rows].sort((a, b) => {
    const av = a[k]
    const bv = b[k]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av).localeCompare(String(bv), 'zh-Hans-CN') * dir
  })
})

const totalPages = computed(() =>
  props.pageSize > 0 ? Math.max(1, Math.ceil(sortedRows.value.length / props.pageSize)) : 1,
)

const pagedRows = computed(() => {
  if (props.pageSize <= 0) return sortedRows.value
  const start = (page.value - 1) * props.pageSize
  return sortedRows.value.slice(start, start + props.pageSize)
})

watch(() => props.rows.length, () => { page.value = 1 })

function keyOf(row: Record<string, unknown>, i: number): string | number {
  const k = row[props.rowKey]
  return typeof k === 'string' || typeof k === 'number' ? k : i
}
</script>

<template>
  <div class="data-table">
    <LoadingBlock v-if="loading" :rows="5" />

    <EmptyGuide v-else-if="!rows.length" :title="emptyTitle" :desc="emptyDesc">
      <template v-if="$slots['empty-action']" #action>
        <slot name="empty-action" />
      </template>
    </EmptyGuide>

    <template v-else>
      <div
        v-if="columnToggle && columns.length >= 4"
        class="data-table__tools"
      >
        <div class="data-table__cols">
          <button
            class="data-table__tool-btn"
            :class="{ 'is-on': showColPicker }"
            title="显示/隐藏列"
            @click="showColPicker = !showColPicker"
          >
            <Icon name="settings" :size="13" />
            <span>列</span>
            <span v-if="hidden.length" class="data-table__cols-badge">{{ hidden.length }}</span>
          </button>
          <div v-if="showColPicker" class="data-table__col-menu" @click.stop>
            <label v-for="c in columns" :key="c.key" class="data-table__col-item">
              <input
                type="checkbox"
                :checked="!hidden.includes(c.key)"
                @change="toggleColumn(c.key)"
              />
              <span>{{ c.title }}</span>
            </label>
            <button class="data-table__col-reset" @click="resetColumns">恢复默认</button>
          </div>
        </div>
      </div>

      <div class="data-table__scroll" @click="showColPicker = false">
        <table class="data-table__table" :class="{ 'is-compact': compact, 'has-hover-actions': hoverActions && !!$slots.actions }">
          <thead>
            <tr>
              <th
                v-for="col in visibleColumns"
                :key="col.key"
                :style="colStyle(col)"
                :class="{ 'is-sortable': col.sortable, 'is-resizing': resizing === col.key }"
                @click="col.sortable && toggleSort(col.key)"
              >
                <span class="data-table__th-inner">
                  {{ col.title }}
                  <Icon
                    v-if="col.sortable && sortKey === col.key"
                    :name="sortDir === 'asc' ? 'chevron-up' : 'chevron-down'"
                    :size="12"
                  />
                </span>
                <span
                  v-if="resizable"
                  class="data-table__grip"
                  title="拖动调整列宽"
                  @mousedown="startResize($event, col.key)"
                  @click.stop
                />
              </th>
              <th v-if="$slots.actions" class="data-table__op-col" aria-label="操作" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in pagedRows"
              :key="keyOf(row, i)"
              @click="emit('rowClick', row)"
            >
              <td
                v-for="col in visibleColumns"
                :key="col.key"
                :style="{ textAlign: col.align || 'left' }"
                :class="[
                  col.cellClass && (typeof col.cellClass === 'function' ? col.cellClass(row) : col.cellClass),
                ]"
              >
                <slot :name="`cell-${col.key}`" :row="row" :value="row[col.key]">
                  {{ col.format ? col.format(row) : (row[col.key] ?? '—') }}
                </slot>
              </td>
              <td v-if="$slots.actions" class="data-table__op-col" @click.stop>
                <div class="data-table__op-inner">
                  <slot name="actions" :row="row" />
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="pageSize > 0 && totalPages > 1" class="data-table__pager">
        <span class="data-table__pager-info">
          共 {{ sortedRows.length }} 条 · 第 {{ page }}/{{ totalPages }} 页
        </span>
        <div class="data-table__pager-btns">
          <button class="data-table__pg" :disabled="page <= 1" @click="page--">上一页</button>
          <button class="data-table__pg" :disabled="page >= totalPages" @click="page++">下一页</button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.data-table { width: 100%; }
.data-table__scroll { width: 100%; overflow-x: auto; }
.data-table__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-md);
}
.data-table__table th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--glass);
  backdrop-filter: blur(10px) saturate(1.15);
  -webkit-backdrop-filter: blur(10px) saturate(1.15);
  padding: 0 var(--sp-4);
  height: 40px;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-sub);
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--border);
  user-select: none;
}
.data-table__table th.is-sortable { cursor: pointer; }
.data-table__table th.is-sortable:hover { color: var(--text); }
.data-table__th-inner { display: inline-flex; align-items: center; gap: 4px; }
.data-table__table td {
  padding: 0 var(--sp-4);
  height: 44px;
  color: var(--text);
  border-bottom: 1px solid var(--border-soft);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.data-table__table.is-compact td { height: 36px; }
.data-table__table tbody tr { position: relative; transition: background var(--dur-fast) var(--ease); }
.data-table__table tbody tr:nth-child(even) { background: var(--row-alt); }
.data-table__table tbody tr:hover { background: var(--bg-hover); }
/* 悬停时左侧 2px 金色强调条（渐变淡入淡出） */
.data-table__table tbody tr:hover::after {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: linear-gradient(180deg, transparent, var(--gold) 45%, transparent);
}
/* 列宽拖拽手柄（默认隐形，悬停/拖拽时出现） */
.data-table__grip {
  position: absolute;
  top: 6px;
  right: -3px;
  width: 7px;
  height: calc(100% - 12px);
  cursor: col-resize;
  border-radius: 2px;
  transition: background var(--dur-fast) var(--ease);
}
.data-table__grip:hover,
.data-table__table th.is-resizing .data-table__grip {
  background: var(--gold);
  opacity: 0.7;
}
.data-table__table th { position: sticky; }
.data-table__table th.is-resizing { color: var(--text); }

/* 表格工具条：列显隐 */
.data-table__tools {
  display: flex;
  justify-content: flex-end;
  padding: 0 var(--sp-4) var(--sp-2);
}
.data-table__cols { position: relative; }
.data-table__tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: var(--control-h-sm);
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--bg);
  color: var(--text-sub);
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease);
}
.data-table__tool-btn:hover { border-color: var(--border-strong); color: var(--text); }
.data-table__tool-btn.is-on { border-color: var(--gold); color: var(--gold); background: var(--gold-dim); }
.data-table__cols-badge {
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: var(--gold);
  color: var(--on-gold);
  font-size: 10px;
  font-weight: 700;
  line-height: 15px;
  text-align: center;
}
.data-table__col-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 40;
  min-width: 150px;
  max-height: 280px;
  overflow-y: auto;
  padding: 6px;
  background: var(--glass);
  backdrop-filter: blur(14px) saturate(1.2);
  -webkit-backdrop-filter: blur(14px) saturate(1.2);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-pop);
}
.data-table__col-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  font-size: var(--fs-sm);
  color: var(--text-sub);
  cursor: pointer;
}
.data-table__col-item:hover { background: var(--bg-hover); color: var(--text); }
.data-table__col-item input { accent-color: var(--gold); }
.data-table__col-reset {
  width: 100%;
  margin-top: 4px;
  padding: 6px 8px;
  border: 0;
  border-top: 1px solid var(--border-soft);
  background: none;
  color: var(--text-faint);
  font-size: var(--fs-xs);
  text-align: left;
  cursor: pointer;
}
.data-table__col-reset:hover { color: var(--gold); }

.data-table__op-col { width: 1%; }
.data-table__op-inner { display: flex; align-items: center; gap: 6px; justify-content: flex-end; }
.data-table__table.has-hover-actions .data-table__op-inner { opacity: 0; transition: opacity var(--dur-fast); }
.data-table__table.has-hover-actions tbody tr:hover .data-table__op-inner { opacity: 1; }
.data-table__pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--text-faint);
}
.data-table__pager-btns { display: flex; gap: 6px; }
.data-table__pg {
  height: var(--control-h-sm);
  padding: 0 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-control);
  background: var(--bg);
  color: var(--text-sub);
  font-size: var(--fs-sm);
  cursor: pointer;
}
.data-table__pg:hover:not(:disabled) {
  border-color: var(--gold);
  color: var(--gold);
  background: var(--gold-dim);
}
.data-table__pg:active:not(:disabled) { transform: scale(0.98); }
.data-table__pg:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
