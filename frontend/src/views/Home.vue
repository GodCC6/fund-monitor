<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, type PortfolioSummary } from '../api'

const router = useRouter()
const portfolios = ref<PortfolioSummary[]>([])
const newName = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    portfolios.value = await api.listPortfolios()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function create() {
  const name = newName.value.trim()
  if (!name) return
  try {
    await api.createPortfolio(name)
    newName.value = ''
    await load()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '创建失败'
  }
}

onMounted(load)
</script>

<template>
  <div class="home">
    <h2>我的组合</h2>

    <div class="create-form">
      <input
        v-model="newName"
        placeholder="新组合名称"
        @keyup.enter="create"
      />
      <button @click="create">创建</button>
    </div>

    <p v-if="loading" class="hint">加载中...</p>
    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="!loading && portfolios.length === 0" class="empty">
      暂无组合，请创建一个
    </div>

    <div
      v-for="p in portfolios"
      :key="p.id"
      class="card"
      @click="router.push(`/portfolio/${p.id}`)"
    >
      <div class="card-name">{{ p.name }}</div>
      <div class="card-date">{{ p.created_at?.slice(0, 10) }}</div>
    </div>
  </div>
</template>

<style scoped>
.home {
  padding-top: 8px;
}

.create-form {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.create-form input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
}

.create-form button {
  padding: 8px 20px;
  background: #1a1a2e;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

.card {
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 10px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: box-shadow 0.2s;
}

.card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.card-name {
  font-size: 16px;
  font-weight: 600;
}

.card-date {
  font-size: 12px;
  color: #999;
}

.hint {
  color: #999;
  text-align: center;
  padding: 20px;
}

.empty {
  color: #999;
  text-align: center;
  padding: 40px 0;
}

.error {
  color: #ff4444;
  text-align: center;
}
</style>
