<script setup lang="ts">
withDefaults(defineProps<{ title: string; subtitle?: string; embedded?: boolean }>(), { embedded: false })
defineSlots<{ right?: {} }>()
</script>

<template>
  <div class="page-header" :class="{ 'page-header--embedded': embedded }">
    <div v-if="!embedded">
      <h1 class="title">{{ title }}</h1>
      <p v-if="subtitle" class="sub">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.right" class="right">
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--sp-5);
  gap: var(--sp-4);
}
.title {
  font-size: var(--fs-xl);
  font-weight: 700;
  color: var(--text);
  margin: 0;
}
.sub {
  margin: var(--sp-1) 0 0;
  color: var(--text-sub);
  font-size: var(--fs-md);
}
.page-header--embedded {
  margin-bottom: var(--sp-3);
  justify-content: flex-end;
}
.right {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex: none;
}
</style>
