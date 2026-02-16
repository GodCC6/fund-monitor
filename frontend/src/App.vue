<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div id="app-container">
    <header class="app-header">
      <h1 @click="router.push('/')">基金估值监控</h1>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-header {
  background: #1a1a2e;
  color: #fff;
  padding: 12px 20px;
  position: sticky;
  top: 0;
  z-index: 100;
}

.app-header h1 {
  margin: 0;
  font-size: 18px;
  cursor: pointer;
}

.app-main {
  max-width: 800px;
  margin: 0 auto;
  padding: 16px;
}
</style>
