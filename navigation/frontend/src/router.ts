import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import ImportView from './views/ImportView.vue'
import BackupView from './views/BackupView.vue'
import ChangePasswordView from './views/ChangePasswordView.vue'
import AdminUsersView from './views/AdminUsersView.vue'
import { clearCurrentUser, refreshCurrentUser } from './session'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/', name: 'workspace', component: WorkspaceView, meta: { requiresAuth: true } },
    { path: '/import', name: 'import', component: ImportView, meta: { requiresAuth: true } },
    { path: '/backups', name: 'backups', component: BackupView, meta: { requiresAuth: true } },
    { path: '/change-password', name: 'change-password', component: ChangePasswordView, meta: { requiresAuth: true } },
    { path: '/admin/users', name: 'admin-users', component: AdminUsersView, meta: { requiresAuth: true, requiresAdmin: true } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true
  try {
    const user = await refreshCurrentUser()
    if (user.must_change_password && to.name !== 'change-password') return { name: 'change-password' }
    if (to.meta.requiresAdmin && !user.is_admin) return { name: 'workspace' }
    return true
  } catch {
    clearCurrentUser()
    return { name: 'login' }
  }
})

window.addEventListener('navigation:unauthorized', () => {
  clearCurrentUser()
  if (router.currentRoute.value.name !== 'login') void router.replace({ name: 'login' })
})

export default router
