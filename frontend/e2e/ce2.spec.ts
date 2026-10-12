import path from 'node:path'
import { expect, test } from '@playwright/test'
import { E2E_TOKEN, SHOTS, STORAGE, WRITE } from './helpers'

test.describe.configure({ mode: 'serial' })

test('sin token de sesión el panel explica cómo entrar y /open lo resuelve', async ({ browser, baseURL }) => {
  // Contexto sin la cabecera de pruebas: como un navegador que abre la dirección a mano.
  const context = await browser.newContext({ baseURL, extraHTTPHeaders: {} })
  const page = await context.newPage()
  await page.goto('/')
  await expect(page.getByRole('alertdialog', { name: 'Abre Video Studio AI desde su lanzador' })).toBeVisible()
  expect((await page.request.get('/api/projects')).status()).toBe(401)
  await page.screenshot({ path: path.join(SHOTS, 'ce2-sesion-requerida.png') })
  // Lo que hace el lanzador: /open?t=… cambia el token por una cookie HttpOnly.
  await page.goto(`/open?t=${E2E_TOKEN}`)
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('alertdialog')).toHaveCount(0)
  const cookies = await context.cookies()
  const session = cookies.find((c) => c.name === 'vsa_session')
  expect(session?.httpOnly).toBe(true)
  expect(session?.sameSite).toBe('Strict')
  expect(await page.evaluate(() => document.cookie)).not.toContain('vsa_session')
  await context.close()
})

test('primera configuración: carpeta, comprobaciones, clave propia y entrada al editor', async ({ page, request }) => {
  // Independiente del orden: si ninguna prueba anterior eligió la carpeta, se elige aquí.
  const storage = await (await request.get('/api/storage/status')).json()
  if (!storage.configured) await request.post('/api/storage/configure', { headers: WRITE, data: { path: STORAGE } })
  await request.post('/api/setup/complete', { headers: WRITE, data: { completed: false } })
  await request.delete('/api/claude/api-key', { headers: WRITE })
  await page.goto('/')
  await expect(page).toHaveURL(/\/setup$/)
  await expect(page.getByRole('heading', { name: 'Bienvenido a Video Studio AI' })).toBeVisible()
  await expect(page.getByText('Carpeta configurada')).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'ce2-setup-1-proyectos.png') })
  await page.getByRole('button', { name: 'Siguiente' }).click()
  await expect(page.getByRole('heading', { name: 'Comprobación del equipo' })).toBeVisible()
  await expect(page.getByText('FFmpeg', { exact: true })).toBeVisible()
  await expect(page.getByText('Transcripción local', { exact: true })).toBeVisible()
  await expect(page.getByText('Remotion (animaciones)', { exact: true })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'ce2-setup-2-equipo.png') })
  await page.getByRole('button', { name: 'Siguiente' }).click()
  await expect(page.getByRole('heading', { name: 'Conexión con Claude' })).toBeVisible()
  await expect(page.getByText(/no incluye el uso de la API/)).toBeVisible()
  await expect(page.getByText(/4 USD por millón de tokens de entrada/)).toBeVisible()
  // Clave de prueba contra la API SIMULADA: se guarda y se comprueba sin coste.
  await page.getByLabel('Clave de API de Anthropic').fill('sk-ant-test-valida-0123456789')
  await page.getByRole('button', { name: 'Guardar clave' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Clave válida' })).toBeVisible()
  await expect(page.getByLabel('Clave de API de Anthropic')).toHaveValue('')
  await page.screenshot({ path: path.join(SHOTS, 'ce2-setup-3-claude.png') })
  // Una clave revocada se explica con claridad.
  await page.getByLabel('Clave de API de Anthropic').fill('sk-ant-test-revoked-0123456789')
  await page.getByRole('button', { name: 'Cambiar clave' }).click()
  await expect(page.getByRole('status').filter({ hasText: /no es válida o fue revocada/ })).toBeVisible()
  await page.getByRole('button', { name: 'Continuar' }).click()
  await expect(page.getByRole('heading', { name: 'Todo listo' })).toBeVisible()
  await page.screenshot({ path: path.join(SHOTS, 'ce2-setup-4-listo.png') })
  await page.getByRole('button', { name: 'Ir al editor' }).click()
  await expect(page).toHaveURL(/\/$/)
  const st = await (await request.get('/api/setup/status')).json()
  expect(st.completed_at).toBeTruthy()
  // Recargar ya no lleva al asistente.
  await page.reload()
  await expect(page).not.toHaveURL(/\/setup$/)
})

test('Ajustes → Claude: cambiar y eliminar la clave con confirmación', async ({ page, request }) => {
  // Las pruebas de fases anteriores usan el CLI simulado: se vuelve al único mecanismo de la CE.
  const prefs = await (await request.get('/api/claude/settings')).json()
  await request.put('/api/claude/settings', { headers: WRITE, data: { ...prefs, transport: 'api', cli_path: null } })
  await request.put('/api/claude/api-key', { headers: WRITE, data: { key: 'sk-ant-test-valida-0123456789' } })
  await page.goto('/settings#claude')
  await expect(page.getByText(/Guardada en/)).toBeVisible()
  await page.getByRole('button', { name: 'Comprobar (sin coste)' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Clave válida' })).toBeVisible()
  page.once('dialog', (d) => void d.accept())
  await page.getByRole('button', { name: 'Eliminar la clave de API' }).click()
  await expect(page.getByText('No configurada')).toBeVisible()
  const st = await (await request.get('/api/claude/status')).json()
  expect(st.api_key_saved).toBe(false)
  await page.screenshot({ path: path.join(SHOTS, 'ce2-ajustes-claude.png') })
})
