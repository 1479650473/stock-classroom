<script setup lang="ts">
import Icon from '@/components/Icon.vue'

/**
 * 指标数字块：标签 + 大数字 + 单位 + 趋势副文本。
 * 用于账户概览、策略指标、行情卡片等所有"数字展示"场景。
 */
withDefaults(
  defineProps<{
    label: string
    value: string | number
    unit?: string
    /** 数值颜色（up=红涨 / down=绿跌 / neutral） */
    trend?: 'up' | 'down' | 'neutral'
    /** 副文本，如涨跌幅 */
    hint?: string
    hintTrend?: 'up' | 'down' | 'neutral'
    icon?: string
  }>(),
  { trend: 'neutral', hintTrend: 'neutral' },
)
</script>

<template>
  <div class="stat-tile">
    <div class="stat-tile__label">
      <Icon v-if="icon" :name="icon" :size="13" />
      <span>{{ label }}</span>
    </div>
    <div class="stat-tile__value num" :class="trend !== 'neutral' ? trend : ''">
      {{ value }}<span v-if="unit" class="stat-tile__unit">{{ unit }}</span>
    </div>
    <div v-if="hint" class="stat-tile__hint" :class="hintTrend !== 'neutral' ? hintTrend : ''">
      {{ hint }}
    </div>
  </div>
</template>

<style scoped>
.stat-tile {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: var(--sp-3);
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}
.stat-tile:hover {
  border-color: var(--border-soft);
  background: color-mix(in srgb, var(--bg-raised) 60%, transparent);
}
.stat-tile__label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-sm);
  color: var(--text-sub);
  white-space: nowrap;
}
.stat-tile__value {
  font-size: var(--fs-2xl);
  font-weight: 650;
  line-height: 1.2;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.stat-tile__unit {
  margin-left: 3px;
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text-sub);
}
.stat-tile__hint { font-size: var(--fs-sm); color: var(--text-faint); }
.up { color: var(--up); }
.down { color: var(--down); }
</style>
