// Shared ECharts lifecycle helper: init once, dispose on unmount,
// auto-resize via ResizeObserver, and redraw when the theme changes
// (colors are resolved from CSS vars at option-build time).
import { onBeforeUnmount, onMounted, shallowRef, type Ref } from 'vue'
import * as echarts from 'echarts'
import { ensureEChartsTheme } from '@/lib/chartTheme'

export function useEChart(el: Ref<HTMLElement | null>, buildOption: () => echarts.EChartsOption) {
  const chart = shallowRef<echarts.ECharts | null>(null)
  let ro: ResizeObserver | null = null
  let mo: MutationObserver | null = null

  function draw() {
    if (!el.value) {
      chart.value?.dispose()
      chart.value = null
      return
    }
    // 容器被重建（如抽屉/弹层关闭再打开、v-if 切换）：旧实例挂在已移除的 DOM 上，
    // 若不重新 init，setOption 会画到脱离文档的容器里 → 新容器永远空白。
    if (chart.value && chart.value.getDom() !== el.value) {
      chart.value.dispose()
      chart.value = null
    }
    if (!chart.value) chart.value = echarts.init(el.value, ensureEChartsTheme())
    chart.value.setOption(buildOption(), true)
  }

  onMounted(() => {
    draw()
    if (el.value) {
      ro = new ResizeObserver(() => chart.value?.resize())
      ro.observe(el.value)
    }
    // 主题切换：重建实例（ECharts 主题只能 init 时注入），再重画一次
    mo = new MutationObserver(() => {
      chart.value?.dispose()
      chart.value = null
      draw()
    })
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  })

  onBeforeUnmount(() => {
    ro?.disconnect()
    mo?.disconnect()
    chart.value?.dispose()
    chart.value = null
  })

  return { chart, draw }
}

// Resolve a CSS var as a fallback-safe color for chart series.
export function cssVar(name: string, fallback = '#D4A574'): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return v || fallback
}
