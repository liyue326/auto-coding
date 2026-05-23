<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import { logout } from '../api/auth';

const router = useRouter();
const loading = ref(false);

const handleLogout = async () => {
  try {
    loading.value = true;
    await logout();
    alert('Logout successful');
    router.push('/login');
  } catch (error) {
    alert('Logout failed: ' + error.message);
  } finally {
    loading.value = false;
  }
};
</script>

<template>
  <div class="login-container">
    <h2>Login</h2>
    <button @click="handleLogout" :disabled="loading">
      {{ loading ? 'Logging out...' : 'Logout' }}
    </button>
  </div>
</template>

<style scoped>
.login-container {
  padding: 20px;
  max-width: 400px;
  margin: 0 auto;
}
</style>
