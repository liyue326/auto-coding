<template>
  <div class="health-view">
    <h1>健康状态</h1>
    <div v-if="loading">加载中...</div>
    <div v-else>{{ status }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { getHealth } from '../api/health';

const status = ref('');
const loading = ref(true);

onMounted(async () => {
  try {
    const response = await getHealth();
    status.value = response.data.status;
  } catch (error) {
    alert('无法获取健康状态');
    console.error(error);
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.health-view {
  text-align: center;
  padding: 20px;
}
</style>
