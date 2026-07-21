import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const adminPassword = process.env.NAV_E2E_ADMIN_PASSWORD ?? 'test-password'
const userPassword = process.env.NAV_E2E_USER_PASSWORD

async function login(page: Page, username: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(username)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/$/)
}

test('admin workbench has independent columns and persistent expand controls', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  await login(page, 'admin', adminPassword)

  await expect(page.locator('.account-link')).toContainText('admin')
  await expect(page.locator('.account-link')).toContainText('管理员')
  await expect(page.locator('[data-test="admin-users"]')).toBeVisible()
  const expandedFolderCount = await page.locator('[data-folder-id]').count()
  expect(expandedFolderCount).toBeGreaterThan(0)

  const positions = await page.evaluate(() => {
    const folder = document.querySelector<HTMLElement>('.drawer-surface')!
    const content = document.querySelector<HTMLElement>('.content-panel')!
    const editor = document.querySelector<HTMLElement>('.editor')!
    const before = {
      page: window.scrollY,
      content: content.scrollTop,
      editor: editor.scrollTop,
    }
    folder.scrollTop = Math.min(600, folder.scrollHeight - folder.clientHeight)
    return {
      before,
      after: {
        page: window.scrollY,
        folder: folder.scrollTop,
        content: content.scrollTop,
        editor: editor.scrollTop,
      },
      shellHeight: document.querySelector<HTMLElement>('.workspace-shell')!.getBoundingClientRect().height,
      viewportHeight: window.innerHeight,
    }
  })
  expect(positions.after.folder).toBeGreaterThan(0)
  expect(positions.after.page).toBe(positions.before.page)
  expect(positions.after.content).toBe(positions.before.content)
  expect(positions.after.editor).toBe(positions.before.editor)
  expect(positions.shellHeight).toBe(positions.viewportHeight)

  await page.locator('[data-test="collapse-all-folders"]').click()
  const collapsedFolderCount = await page.locator('[data-folder-id]').count()
  expect(collapsedFolderCount).toBeGreaterThan(0)
  expect(collapsedFolderCount).toBeLessThan(expandedFolderCount)
  await page.reload()
  await expect(page.locator('[data-folder-id]')).toHaveCount(collapsedFolderCount)
  await page.locator('[data-test="expand-all-folders"]').click()
  await expect(page.locator('[data-folder-id]')).toHaveCount(expandedFolderCount)

  await page.locator('[data-test="admin-users"]').click()
  await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
  await expect(
    page.getByRole('cell', { name: 'acceptance-user 普通用户' }).getByText('acceptance-user', { exact: true }),
  ).toBeVisible()
})

test('ordinary user sees only their isolated bookmark and no admin route', async ({ page }) => {
  test.skip(!userPassword, 'NAV_E2E_USER_PASSWORD is required for the multi-user check')
  await login(page, 'acceptance-user', userPassword!)
  await expect(page.locator('.account-link')).toContainText('acceptance-user')
  await expect(page.locator('[data-test="admin-users"]')).toHaveCount(0)
  await expect(page.locator('[data-folder-id]')).toHaveCount(1)
  await expect(page.getByRole('heading', { name: 'Acceptance isolated bookmark' })).toBeVisible()
  await page.goto('/admin/users')
  await expect(page).toHaveURL(/\/$/)
})
