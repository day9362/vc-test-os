<script setup lang="ts">
defineProps<{ title: string; desc?: string }>()
</script>

<template>
  <div class="ph">
    <div class="grow">
      <h2>{{ title }}</h2>
      <p v-if="desc" class="muted fs-sm">{{ desc }}</p>
    </div>
    <div class="row wrap"><slot /></div>
  </div>
</template>

<style scoped>
.ph { display: flex; align-items: flex-end; gap: 12px; flex-wrap: wrap; padding-bottom: 2px; }
.ph h2 { font-size: var(--fs-xl); font-weight: 700; letter-spacing: 0.01em; }
</style>
