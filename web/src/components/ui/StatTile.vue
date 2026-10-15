<script setup lang="ts">
import { ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import AnimatedNumber from '@/components/ui/AnimatedNumber.vue'

/**
 * 指标数字块：标签 + 大数字 + 单位 + 趋势副文本。
 * 用于账户概览、策略指标、行情卡片等所有"数字展示"场景。
 */
const props = withDefaults(
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

function toneClass(trend: string, value: string | number): string {
  if (trend === 'neutral') return ''
  const n = typeof value === 'number'
    ? value
    : Number(String(value).replace(/,/g, '').replace('%', ''))
  return Number.isFinite(n) && n === 0 ? '' : trend
}

/**
 * 数值变化时做一次"上浮重入"，让"数据刷新了"这件事看得见。
 *
 * 为什么要用递增 key 而不是切 class：动画只在**元素重新创建**或 class 由无到有时触发。
 * 连续两次更新如果只是同一个 class，第二次不会重播 —— 表现为"只有第一次刷新有反馈"。
 * 递增 key 让 Vue 每次都换新节点，动画必然重播（代价只是这个 span 重建，可忽略）。
 *
 * 首次挂载不播（值本来就从空到有，那时页面入场的级联已经在动了，会重叠）。
 */
const tick = ref(0)
let mounted = false
watch(() => props.value, () => { if (mounted) tick.value++ })
</script>

<template>
  <div class="stat-tile">
    <div class="stat-tile__label">
      <Icon v-if="icon" :name="icon" :size="13" />
      <span>{{ label }}</span>
    </div>
    <div class="stat-tile__value num" :class="toneClass(trend, value)">
      <!-- key=tick：值每次变化都换新节点，保证 m-tick 动画必然重播（见脚本注释） -->
      <span :key="tick" :class="{ 'm-tick': tick > 0 }">
        <AnimatedNumber v-if="raw !== undefined" :value="raw" :format="format" />
        <template v-else>{{ value }}</template>
      </span><span v-if="unit" class="stat-tile__unit">{{ unit }}</span>
    </div>
    <div v-if="hint" class="stat-tile__hint" :class="toneClass(hintTrend, hint)">
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
