<script setup lang="ts">
// 选股依据明细：候选池来源 / 过滤规则 / 打分口径 / 候选清单 / 事件池
// 目的：让「候选股是怎么来的」完全可核对，不做黑箱。
import type { CandSnapshot, CandPick } from '@/lib/cands'
import { filtersOn, filtersOff, groupWeights, funnelText } from '@/lib/cands'

const props = defineProps<{ cands: CandSnapshot; picked?: Set<string>; compact?: boolean }>()

const picks = () => (props.cands.picks || []).slice(0, props.compact ? 8 : 20)
const groupText = (p: CandPick) => (p.groups || []).map((g) => `${g.name} ${g.score}`).join(' · ')
</script>

<template>
  <div class="cand">
    <div class="cand__meta">
      <div class="crow"><span class="ck">候选来源</span><span class="cv">{{ cands.universe || '—' }}</span></div>
      <div class="crow"><span class="ck">筛选链路</span><span class="cv">{{ cands.chain || '—' }}</span></div>
      <div class="crow"><span class="ck">生效过滤</span><span class="cv">{{ filtersOn(cands).join(' · ') || '无' }}</span></div>
      <div v-if="filtersOff(cands).length" class="crow">
        <span class="ck">未启用</span><span class="cv cv--dim">{{ filtersOff(cands).join(' · ') }}</span></div>
      <div class="crow">
        <span class="ck">评分口径</span>
        <span class="cv">
          {{ cands.scorecard?.name || '多因子评分卡' }} · 窗口 {{ cands.scorecard?.data_window ?? '—' }} 个交易日
          <template v-if="groupWeights(cands)">（{{ groupWeights(cands) }}）</template>
        </span>
      </div>
      <div class="crow"><span class="ck">筛选漏斗</span><span class="cv">{{ funnelText(cands).join(' → ') || '—' }}</span></div>
      <div v-if="(cands.hot_sectors || []).length" class="crow">
        <span class="ck">热点板块</span><span class="cv">{{ (cands.hot_sectors || []).join(' · ') }}</span></div>
    </div>

    <table class="ctable">
      <thead>
        <tr><th class="ta-r">#</th><th>候选股</th><th class="ta-r">总分</th><th>分项</th><th>模型操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="p in picks()" :key="p.code" :class="{ 'is-picked': picked?.has(p.code) }">
          <td class="ta-r">{{ p.rank }}</td>
          <td><b>{{ p.name }}</b> <span class="csub">{{ p.code }}</span></td>
          <td class="ta-r"><b>{{ p.score }}</b></td>
          <td class="csub">{{ groupText(p) }}</td>
          <td>{{ picked?.has(p.code) ? '模型当日操作' : '' }}</td>
        </tr>
        <tr v-if="!picks().length"><td colspan="5" class="csub">当日候选池不可用</td></tr>
      </tbody>
    </table>

    <div v-if="(cands.events || []).length" class="cevents">
      <span class="ck">事件驱动池</span>
      <div class="cevents__list">
        <div v-for="(e, i) in cands.events" :key="i" class="cevent">
          <b>{{ e.name || e.code }}</b> <span class="csub">{{ e.reason }}</span>
        </div>
      </div>
    </div>
    <div v-if="cands.error" class="cwarn">{{ cands.error }}</div>
  </div>
</template>

<style scoped>
.cand { display: flex; flex-direction: column; gap: 8px; }
.cand__meta { display: flex; flex-direction: column; gap: 3px; }
.crow { display: grid; grid-template-columns: 78px 1fr; gap: 8px; align-items: start; font-size: 12px; }
.ck { color: var(--fg-dim); white-space: nowrap; }
.cv { color: var(--fg); line-height: 1.5; }
.cv--dim { color: var(--fg-dim); }
.ctable { width: 100%; border-collapse: collapse; font-size: 12px; }
.ctable th { text-align: left; color: var(--fg-dim); font-weight: 500; padding: 3px 6px; border-bottom: 1px solid var(--line); }
.ctable td { padding: 3px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
.ctable tr.is-picked td { background: color-mix(in srgb, var(--accent) 10%, transparent); }
.ctable .ta-r { text-align: right; }
.csub { color: var(--fg-dim); font-size: 11px; }
.cevents { display: grid; grid-template-columns: 78px 1fr; gap: 8px; font-size: 12px; }
.cevents__list { display: flex; flex-direction: column; gap: 2px; }
.cevent { line-height: 1.5; }
.cwarn { font-size: 12px; color: var(--accent); }
@media (max-width: 900px) { .crow, .cevents { grid-template-columns: 1fr; } }
</style>
