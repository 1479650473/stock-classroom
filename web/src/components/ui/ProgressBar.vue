<script setup lang="ts">
/**
 * 进度条：把「任务在跑」这件事画出来，而不是只显示一行文字 + 百分号。
 *
 * 三种状态：
 *   · 确定进度：width 随 pct 平滑过渡（transition，不是硬跳）
 *   · 运行中：叠一道流光，表达"正在推进"
 *   · 进度未知（pct 为 null/undefined）：走**不确定态**（来回扫），
 *     而不是傻停在 0% —— 停着会让用户以为卡死了
 *
 * 只用 transform / opacity 与 width 的 transition：width 会触发布局，
 * 但进度条本身是独立小元素且用 transform 承载流光，实际开销可忽略。
 */
const props = withDefaults(
  defineProps<{
    /** 0-100；传 null/undefined 表示进度未知 → 不确定态 */
    pct?: number | null
    /** 是否正在运行（决定要不要流光/呼吸） */
    active?: boolean
    /** 高度 */
    size?: 'sm' | 'md'
    /** 主文案（如"更新 K 线中…"） */
    label?: string
    /** 右侧补充（如"320/5548"） */
    note?: string
    /** 已完成：变成功色 */
    done?: boolean
    /** 失败：变失败色 */
    error?: boolean
  }>(),
  { pct: null, active: false, size: 'sm', done: false, error: false },
)

import { computed } from 'vue'

/** 是否处于"不确定态"：没有有效数字，但任务在跑 */
const indeterminate = computed(() => props.active && (props.pct === null || props.pct === undefined || Number.isNaN(props.pct)))

/** 夹到 0-100，避免脏数据把条画到框外 */
const width = computed(() => {
  if (props.pct === null || props.pct === undefined || Number.isNaN(props.pct)) return 0
  return Math.max(0, Math.min(100, props.pct))
})

const tone = computed(() => (props.error ? 'is-error' : props.done ? 'is-done' : ''))
const showPct = computed(() => typeof props.pct === 'number' && !Number.isNaN(props.pct))
</script>

<template>
  <div class="pbar" :class="[`pbar--${size}`, tone, { 'is-active': active && !done && !error }]">
    <div
      v-if="label || note || showPct"
      class="pbar__meta"
    >
      <span v-if="label" class="pbar__label">{{ label }}</span>
      <span v-if="note" class="pbar__note mono">{{ note }}</span>
      <span v-if="showPct" class="pbar__pct mono">{{ Math.round(width) }}%</span>
    </div>
    <div
      class="pbar__track"
      role="progressbar"
      :aria-valuenow="indeterminate ? undefined : Math.round(width)"
      aria-valuemin="0"
      aria-valuemax="100"
    >
      <!-- 不确定态：一段固定宽度的滑块来回扫（m-sweep 关键帧在动效层） -->
      <i v-if="indeterminate" class="pbar__sweep" />
      <i v-else class="pbar__fill" :style="{ width: width + '%' }" />
    </div>
  </div>
</template>

<style scoped>
.pbar { display: flex; flex-direction: column; gap: 5px; }
.pbar__meta {
  display: flex; align-items: baseline; gap: var(--sp-2);
  font-size: var(--fs-xs); color: var(--text-sub);
}
.pbar__label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pbar__note { color: var(--text-faint); }
.pbar__pct { color: var(--text-sub); font-variant-numeric: tabular-nums; }

.pbar__track {
  position: relative;
  overflow: hidden;
  border-radius: var(--radius-pill);
  background: var(--bg-overlay);
}
.pbar--sm .pbar__track { height: 4px; }
.pbar--md .pbar__track { height: 7px; }

.pbar__fill {
  display: block; height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent), var(--accent-hover, var(--accent)));
  /* 宽度平滑过渡：进度从 12%→37% 是"滑过去"而不是"跳过去" */
  transition: width var(--dur) var(--ease-out), background var(--dur) var(--ease);
}

/* 确定态下的流光：叠在填充条上，表达"还在推进" */
.pbar.is-active .pbar__fill {
  background-image: linear-gradient(
    100deg,
    transparent 25%,
    color-mix(in srgb, #fff 45%, transparent) 50%,
    transparent 75%
  );
  background-size: 220% 100%;
  background-repeat: no-repeat;
  animation: m-progress-sheen 1.6s linear infinite;
}

/* 不确定态滑块 */
.pbar__sweep {
  position: absolute; inset: 0 auto 0 0;
  width: 38%; height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: m-sweep 1.25s var(--ease) infinite;
}

.pbar.is-done .pbar__fill { background: var(--ok); animation: none; }
.pbar.is-error .pbar__fill { background: var(--up); animation: none; }

@media (prefers-reduced-motion: reduce) {
  .pbar__fill { transition: none; }
  .pbar.is-active .pbar__fill { animation: none; }
  .pbar__sweep { animation: none; width: 100%; opacity: 0.35; }
}
:root[data-motion='reduced'] .pbar__fill { transition: none; }
:root[data-motion='reduced'] .pbar.is-active .pbar__fill { animation: none; }
:root[data-motion='reduced'] .pbar__sweep { animation: none; width: 100%; opacity: 0.35; }
</style>
