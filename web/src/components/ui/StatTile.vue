<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import AnimatedNumber from '@/components/ui/AnimatedNumber.vue'

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
    /** 传原始数值即可启用数字滚动（value 仍作为非动画回退/无障碍文本） */
    raw?: number
    /** 数字滚动的格式化函数 */
    format?: (n: number) => string
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
      <AnimatedNumber v-if="raw !== undefined" :value="raw" :format="format" />
      <template v-else>{{ value }}</template><span v-if="unit" class="stat-tile__unit">{{ unit }}</span>
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
}
.stat-tile__value { letter-spacing: -0.01em; }
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
