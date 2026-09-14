<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'

const { lang } = useData()

const placeholder = computed(() =>
  lang.value.startsWith('zh') ? '搜索文档' : 'Search docs'
)

function openSearch() {
  document
    .querySelector<HTMLButtonElement>('.VPNavBarSearch button')
    ?.click()
}
</script>

<template>
  <div class="sidebar-search">
    <button
      type="button"
      class="sidebar-search-btn"
      :aria-label="placeholder"
      @click="openSearch"
    >
      <span class="vpi-search sidebar-search-icon" aria-hidden="true" />
      <span class="sidebar-search-text">{{ placeholder }}</span>
      <span class="sidebar-search-kbd">Ctrl K</span>
    </button>
  </div>
</template>

<style scoped>
.sidebar-search {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 16px 0 10px;
  background-color: var(--vp-sidebar-bg-color);
}

@media (min-width: 960px) {
  .sidebar-search {
    top: 0;
  }
}

.sidebar-search-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 8px;
  background-color: var(--vp-c-bg-soft);
  color: var(--vp-c-text-2);
  font-size: 14px;
  cursor: pointer;
  transition:
    border-color 0.25s,
    color 0.25s;
}

.sidebar-search-btn:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-text-1);
}

.sidebar-search-btn:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.sidebar-search-icon {
  font-size: 16px;
  color: var(--vp-c-text-3);
}

.sidebar-search-btn:hover .sidebar-search-icon {
  color: var(--vp-c-brand-1);
}

.sidebar-search-text {
  flex: 1;
  text-align: left;
}

.sidebar-search-kbd {
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 4px;
  color: var(--vp-c-text-3);
  background-color: var(--vp-c-bg);
}

@media (any-pointer: coarse) {
  .sidebar-search-kbd {
    display: none;
  }
}
</style>
