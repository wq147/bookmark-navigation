import { ref } from 'vue'
import { apiClient } from './api'
import type { User } from './types'

export const currentUser = ref<User | null>(null)

export async function refreshCurrentUser(): Promise<User> {
  const user = await apiClient.me()
  currentUser.value = user
  return user
}

export function clearCurrentUser(): void {
  currentUser.value = null
}
