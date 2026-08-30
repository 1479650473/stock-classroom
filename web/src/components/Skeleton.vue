<template>
  <div class="skeleton">
    <div class="sk-row" />
    <div class="sk-row short" />
    <div class="sk-row" />
  </div>
</template>

<style scoped>
.skeleton { display: flex; flex-direction: column; gap: var(--sp-3); padding: var(--sp-4); }
.sk-row {
  height: 16px;
  background: var(--bg-raised);
  border-radius: var(--radius-sm);
  animation: shimmer 1.5s ease-in-out infinite;
}
.sk-row.short { width: 60%; }
@keyframes shimmer {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
</style>
