<script setup lang="ts">
import Icon from './Icon.vue'

defineProps<{
  label: string
  value: string | number
  unit?: string
  trend?: 'up' | 'down' | 'flat'
  trendValue?: string
  icon?: string
}>()
</script>

<template>
  <div class="stat-card" :class="trend">
    <div class="hd">
      <Icon v-if="icon" :name="icon" :size="15" class="ic" />
      <span class="label">{{ label }}</span>
    </div>
    <div class="val num">
      {{ value }}<span v-if="unit" class="unit">{{ unit }}</span>
    </div>
    <div v-if="trendValue" class="trend-row">
      <span class="trend num" :class="trend">{{ trendValue }}</span>
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  transition: transform var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}
.stat-card:hover {
  transform: translateY(-1px);
  border-color: var(--border);
  box-shadow: var(--shadow-card);
}
.hd {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.ic { color: var(--text-faint); }
.label { font-size: var(--fs-sm); color: var(--text-sub); letter-spacing: 0.04em; }
.val {
  font-size: var(--fs-2xl);
  font-weight: 600;
  color: var(--text);
  margin: var(--sp-1) 0;
}
.unit { font-size: var(--fs-sm); color: var(--text-faint); margin-left: 2px; }
.trend { font-size: var(--fs-sm); font-weight: 600; }
.trend.up { color: var(--up); }
.trend.down { color: var(--down); }
.trend.flat { color: var(--text-faint); }
</style>
