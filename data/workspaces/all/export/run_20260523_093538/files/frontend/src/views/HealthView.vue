<template>
  <div>
    <h1>健康状态</h1>
    <p>当前时间: {{ currentTime }}</p>
    <!-- 假设这是健康状态数据 -->
    <div v-if="healthData">
      <p>心率: {{ healthData.heartRate }} bpm</p>
      <p>血压: {{ healthData.bloodPressure }} mmHg</p>
      <p>血氧: {{ healthData.oxygenLevel }} %</p>
    </div>
    <div v-else>
      <p>加载健康数据...</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { getHealthData } from '@/api/health';

const healthData = ref(null);
const currentTime = ref('');

// 获取当前时间
function updateCurrentTime() {
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const seconds = String(now.getSeconds()).padStart(2, '0');
  currentTime.value = `${hours}:${minutes}:${seconds}`;
}

// 获取健康数据
async function fetchHealthData() {
  try {
    const data = await getHealthData();
    healthData.value = data;
  } catch (error) {
    alert('无法获取健康数据');
  }
}

onMounted(() => {
  // 初始化时间
  updateCurrentTime();
  // 每秒更新时间
  const interval = setInterval(updateCurrentTime, 1000);
  
  // 获取健康数据
  fetchHealthData();

  // 清理定时器
  return () => {
    clearInterval(interval);
  };
});
</script>

<style scoped>
/* 可以添加样式 */
</style>
