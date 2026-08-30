<script setup lang="ts">
defineProps<{ rows: Record<string, unknown>[]; columns: { key: string; label: string; align?: 'left' | 'right'; format?: (v: unknown, row: Record<string, unknown>) => string }[] }>()
</script>

<template>
  <div class="table-wrap">
    <table class="table">
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            :class="['th', col.align === 'right' ? 'ar' : 'al']"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="i" class="tr">
          <td
            v-for="col in columns"
            :key="col.key"
            :class="['td', 'num', col.align === 'right' ? 'ar' : 'al']"
          >
            {{ col.format ? col.format(row[col.key], row) : (row[col.key] ?? '—') }}
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="!rows.length" class="empty">暂无数据</div>
  </div>
</template>

<style scoped>
.table-wrap { overflow-x: auto; }
.table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.th {
  padding: 10px var(--sp-3);
  font-weight: 600;
  color: var(--text-sub);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  text-align: left;
}
.th.ar { text-align: right; }
.tr:hover { background: var(--bg-hover); }
.td {
  padding: 10px var(--sp-3);
  border-bottom: 1px solid var(--border-soft);
  white-space: nowrap;
  color: var(--text);
}
.td.ar { text-align: right; }
.empty { text-align: center; padding: var(--sp-8); color: var(--text-faint); }
</style>
