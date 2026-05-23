import { createRouter, createWebHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/login" },
  { path: "/login", component: () => import("../views/LoginView.vue") },
];

export default createRouter({
  history: createWebHistory(),
  routes,
});
