import { existsSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { AnimationsState, EngineStatus, ProjectSummary } from '../src/lib/types'
import { api, media, sha256, SHOTS, STORAGE } from './helpers'

// Fase 4: motor de animaciones desde el panel, sobre el plan aprobado en la Fase 3.
// El render es real (Remotion + navegador de render instalado en el equipo, enlazado al entorno
// de pruebas por run-e2e.sh). La dirección de Claude usa el CLI simulado salvo VSA_E2E_CLAUDE=1.
test.describe.configure({ mode: 'serial' })

const NAME = 'voz_es'
const H = { 'X-VSA-Client': '1' }
const FAKE = process.env.VSA_E2E_FAKE_CLAUDE ?? ''
const REAL = process.env.VSA_E2E_CLAUDE === '1'

const shot = async (page: Page, name: string) => {
  await page.waitForTimeout(600)
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

async function projectId(page: Page) {
  return (await api<ProjectSummary[]>(page, '/api/projects')).find((p) => p.name === NAME)!.id
}

async function state(page: Page) {
  return api<AnimationsState>(page, `/api/projects/${await projectId(page)}/animations`)
}

test.beforeAll(async ({ request }) => {
  const engine = (await (await request.get('/api/animations/engine')).json()) as EngineStatus
  test.skip(!engine.ready, 'El motor de animaciones no está instalado en este equipo')
  if (!REAL) {
    test.skip(!FAKE || !existsSync(FAKE), 'Falta el CLI simulado (usa «npm run e2e»)')
    const prefs = await (await request.get('/api/claude/settings')).json()
    await request.put('/api/claude/settings', { data: { ...prefs, transport: 'claude_code', cli_path: FAKE }, headers: H })
  }
})

test('Ajustes → Animaciones: estado del motor y efectos de sonido', async ({ page }) => {
  await page.goto('/settings')
  const section = page.locator('#engine')
  await section.scrollIntoViewIfNeeded()
  await expect(section.getByText('Listo', { exact: true })).toBeVisible()
  await expect(section.getByText(/Chrome Headless Shell.*157\.0\.8080\.0/)).toBeVisible()
  await expect(section.getByText(/v4\.0\.534/)).toBeVisible()
  await expect(section.getByRole('button', { name: 'Escuchar Pop' })).toBeVisible()
  const wav = await page.request.get('/api/animations/sfx/whoosh')
  expect(wav.headers()['content-type']).toBe('audio/wav')
  await section.screenshot({ path: path.join(SHOTS, 'p4-01-motor.png') })
})

test('generar las animaciones del plan aprobado, ver el progreso y previsualizar', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  const before = sha256(media('voz_es.mp4'))
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await page.getByRole('tab', { name: 'Plan IA' }).click()
  const section = page.getByRole('region', { name: 'Animaciones del plan aprobado' })
  await expect(section).toBeVisible()
  const initial = await state(page)
  expect(initial.approved_version).not.toBeNull()
  const animated = initial.items.filter((i) => i.status !== 'kept')
  expect(animated.length).toBeGreaterThan(0)
  await section.getByRole('button', { name: 'Generar animaciones' }).click()
  await expect(section.getByRole('status')).toBeVisible()
  await shot(page, 'p4-02-generando')
  await expect.poll(async () => (await state(page)).job, { timeout: 600_000, intervals: [2000] }).toBeNull()
  const done = await state(page)
  for (const it of done.items.filter((i) => i.status !== 'kept')) {
    expect(it.status).toBe('ready')
    expect(it.direction).toBe('claude')
    expect(it.size?.[0]).toBe(720) // tamaño del original (720×1280), sin reescalar
  }
  await expect(section.getByText('Disponible').first()).toBeVisible()
  // Línea de tiempo: punto de estado de la animación en el carril del plan.
  await expect(page.locator('[data-plan-id] [title="Animación: disponible"]').first()).toBeVisible()
  await shot(page, 'p4-03-disponibles')
  // Vista previa real del tramo y comparación con el original.
  await section.getByRole('button', { name: 'Vista previa' }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Vista previa de la animación' })
  await expect(dialog).toBeVisible({ timeout: 120_000 })
  await expect(dialog.getByText(/no es el render final/)).toBeVisible()
  const video = dialog.locator('video[aria-label="Vista previa editada"]')
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 30_000 }).toBeGreaterThanOrEqual(2)
  await shot(page, 'p4-04-vista-previa')
  await dialog.getByRole('radio', { name: 'Original' }).click()
  await expect(dialog.locator('video[aria-label="Tramo original"]')).toBeVisible()
  await page.keyboard.press('Escape')
  expect(sha256(media('voz_es.mp4'))).toBe(before)
})

test('exportar con animaciones desde el diálogo de exportación', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  const before = sha256(media('voz_es.mp4'))
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await page.getByRole('button', { name: 'Exportar', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Exportar video' })
  const sw = dialog.getByRole('switch', { name: 'Incluir animaciones' })
  await expect(sw).toBeChecked()
  await expect(dialog.getByText(/animaciones del plan aprobado/)).toBeVisible()
  await shot(page, 'p4-05-exportar')
  const id = await projectId(page)
  const previous = (await api<unknown[]>(page, `/api/projects/${id}/exports`)).length
  await dialog.getByRole('button', { name: 'Exportar', exact: true }).click()
  // La exportación nueva (no las anteriores de la Fase 2) debe terminar bien.
  await expect
    .poll(async () => {
      const list = await api<{ status: string }[]>(page, `/api/projects/${id}/exports`)
      return list.length > previous ? list[0].status : 'pendiente'
    }, { timeout: 600_000, intervals: [2000] })
    .toBe('succeeded')
  const exports = await api<{ status: string; file_rel: string; width: number; height: number; settings: { with_animations: boolean; animations: { animations: number; plan_version: number } } }[]>(page, `/api/projects/${id}/exports`)
  expect(exports[0].status).toBe('succeeded')
  expect(exports[0].settings.with_animations).toBe(true)
  expect(exports[0].settings.animations.animations).toBeGreaterThan(0)
  expect([exports[0].width, exports[0].height]).toEqual([720, 1280])
  expect(existsSync(path.join(STORAGE, exports[0].file_rel))).toBe(true)
  await dialog.getByRole('button', { name: 'Ver' }).first().click()
  const preview = page.locator('video[aria-label="Vista previa de la exportación"]')
  await expect.poll(() => preview.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 30_000 }).toBeGreaterThanOrEqual(2)
  await shot(page, 'p4-06-exportado')
  expect(sha256(media('voz_es.mp4'))).toBe(before)
})
