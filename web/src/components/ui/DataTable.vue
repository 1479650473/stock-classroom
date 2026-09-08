<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  }>(),
  {
    rowKey: 'id',
    loading: false,
    emptyTitle: '暂无数据',
    pageSize: 0,
    compact: false,
    hoverActions: true,
  },
)

const emit = defineEmits<{ rowClick: [row: Record<string, unknown>] }>()

const sortKey = ref('')
const sortDir = ref<'asc' | 'desc'>('asc')
const page = ref(1)

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
      <div class="data-table__scroll">
        <table class="data-table__table" :class="{ 'is-compact': compact, 'has-hover-actions': hoverActions && !!$slots.actions }">
          <thead>
            <tr>
              <th
                v-for="col in columns"
                :key="col.key"
                :style="{ width: col.width, textAlign: col.align || 'left' }"
                :class="{ 'is-sortable': col.sortable }"
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
                v-for="col in columns"
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
.data-table__table tbody tr { transition: background var(--dur-fast) var(--ease); }
.data-table__table tbody tr:hover { background: var(--bg-hover); }
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
.data-table__pg:hover:not(:disabled) { border-color: var(--gold); color: var(--gold); }
.data-table__pg:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
