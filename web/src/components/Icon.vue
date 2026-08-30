<script setup lang="ts">
import { computed } from 'vue'
import { ICONS } from '@/lib/icons'

const props = withDefaults(defineProps<{ name: string; size?: number; strokeWidth?: number }>(), {
  size: 18,
  strokeWidth: 1.8,
})

const inner = computed(() => ICONS[props.name] ?? ICONS.dot)
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="icon"
    v-html="inner"
  ></svg>
</template>

<style scoped>
.icon { display: inline-block; flex: none; vertical-align: middle; }
</style>
