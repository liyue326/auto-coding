import { createRouter, createWebHistory } from 'vue-router';
import LoginView from '../views/LoginView.vue';
import HealthView from '../views/HealthView.vue';
import NotesView from '../views/NotesView.vue';

const routes = [
  { path: '/', redirect: '/login' },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/health', name: 'health', component: HealthView },
  { path: '/notes', name: 'notes', component: NotesView },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
