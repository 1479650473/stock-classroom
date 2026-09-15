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
