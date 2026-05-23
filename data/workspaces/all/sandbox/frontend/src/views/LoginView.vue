<template>
  <div class="login-page">
    <h1>登录 / 注册</h1>
    <input v-model="username" placeholder="用户名" />
    <input v-model="password" type="password" placeholder="密码" />
    <input v-model="email" placeholder="邮箱" />
    <button :disabled="loading" @click="onLogin">登录</button>
    <button :disabled="loading" @click="onRegister">注册</button>
    <p>{{ msg }}</p>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { login, register } from "../api/auth.js";

const username = ref("");
const password = ref("");
const email = ref("");
const msg = ref("");
const loading = ref(false);

async function onLogin() {
  loading.value = true;
  try {
    const data = await login({ username: username.value, password: password.value });
    msg.value = `登录成功: ${data.token}`;
  } catch (e) {
    msg.value = String(e);
  } finally {
    loading.value = false;
  }
}

async function onRegister() {
  loading.value = true;
  try {
    await register({
      username: username.value,
      password: password.value,
      email: email.value,
    });
    msg.value = "注册成功";
  } catch (e) {
    msg.value = String(e);
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page { max-width: 400px; margin: 2rem auto; }
input { display: block; width: 100%; margin: 0.5rem 0; padding: 0.5rem; }
</style>
