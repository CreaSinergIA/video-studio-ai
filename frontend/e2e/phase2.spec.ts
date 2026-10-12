import { existsSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { AnalysisState, ProjectSummary } from '../src/lib/types'
import { api, media, sha256, SHOTS, STORAGE, uploadViaBrowser, waitProjectReady } from './helpers'

// Fase 2: flujo completo desde el panel (sin terminal). Requiere un modelo instalado en
// VSA_E2E_MODELS; si no está, la prueba descarga el modelo desde el propio panel.
test.describe.configure({ mode: 'serial' })

const NAME = 'voz_es'
const shot = async (page: Page, name: string) => {
  await page.waitForTimeout(700)
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

async function projectId(page: Page): Promise<string> {
  const projects = await api<ProjectSummary[]>(page, '/api/projects')
  return projects.find((p) => p.name === NAME)?.id as string
}

async function openEditor(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await expect(page.getByRole('button', { name: /^Renombrar proyecto/ })).toBeVisible()
}

async function videoTime(page: Page) {
  return page.locator('video').evaluate((v: HTMLVideoElement) => v.currentTime)
}

test('modelo de transcripción disponible (descarga explícita desde Ajustes si falta)', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada (macOS «say»)')
  await page.goto('/settings#analysis')
  const section = page.locator('#analysis')
  await expect(section.getByRole('heading', { name: 'Transcripción y análisis' })).toBeVisible()
  const models = await api<{ models: { id: string; installed: boolean }[] }>(page, '/api/asr/models')
  if (!models.models.find((m) => m.id === 'large-v3-turbo')?.installed) {
    await section.getByRole('button', { name: 'Descargar' }).first().click()
    await expect(section.getByText('Instalado').first()).toBeVisible({ timeout: 600_000 })
  }
  await expect(section.getByText('Instalado').first()).toBeVisible()
  await shot(page, 'p2-01-modelos')
})

test('importar y analizar desde el panel: transcripción, escenas y fotogramas', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada')
  await page.goto('/')
  await uploadViaBrowser(page, [media('voz_es.mp4')])
  await waitProjectReady(page, NAME)
  await openEditor(page)
  await page.getByRole('button', { name: 'Analizar video' }).click()
  await expect(page.getByRole('button', { name: 'Analizando…' })).toBeVisible()
  await shot(page, 'p2-02-analizando')
  const id = await projectId(page)
  await expect
    .poll(async () => {
      const st = await api<AnalysisState>(page, `/api/projects/${id}/analysis`)
      return Boolean(st.transcript && st.visual)
    }, { timeout: 300_000, intervals: [2000] })
    .toBe(true)
  await page.getByRole('tab', { name: 'Transcripción' }).click()
  const panel = page.getByRole('tabpanel')
  await expect(panel.getByText('Transcripción original')).toBeVisible()
  await expect(panel.getByText('Español')).toBeVisible()
  await expect(panel.getByRole('button', { name: /^bienvenidos/i })).toBeVisible()
  await expect(panel.getByRole('button', { name: /^inteligencia/i })).toBeVisible()
  await page.getByRole('tab', { name: 'Análisis' }).click()
  await expect(page.getByRole('tabpanel').getByText('Escena 2')).toBeVisible()
  await expect(page.getByRole('tabpanel').getByText('Corte').first()).toBeVisible()
  await shot(page, 'p2-03-analisis')
})

test('transcripción sincronizada: clic en palabra, subtítulos en el reproductor', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada')
  await openEditor(page)
  await page.getByRole('tab', { name: 'Transcripción' }).click()
  const word = page.getByRole('tabpanel').getByRole('button', { name: /^inteligencia/i })
  const id = await projectId(page)
  const st = await api<AnalysisState>(page, `/api/projects/${id}/analysis`)
  const truth = st.transcript!.segments.flatMap((s) => s.words).find((w) => /^inteligencia/i.test(w.text))!
  await word.click()
  await expect.poll(() => videoTime(page)).toBeGreaterThan(truth.start - 0.05)
  expect(await videoTime(page)).toBeLessThan(truth.start + 0.1)
  // La palabra activa se resalta en el texto y aparece en los subtítulos del reproductor.
  await expect(word).toHaveClass(/bg-accent/)
  const overlay = page.locator('video').locator('xpath=..').getByText(/inteligencia/i)
  await expect(overlay.first()).toBeVisible()
  await shot(page, 'p2-04-transcripcion-sincronizada')
})

test('corregir texto: tiempos conservados, estimados marcados y realineado con el audio', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada')
  await openEditor(page)
  await page.getByRole('tab', { name: 'Transcripción' }).click()
  const panel = page.getByRole('tabpanel')
  const first = panel.locator('li').first()
  await first.hover()
  await first.getByRole('button', { name: 'Corregir texto del segmento' }).click()
  const area = panel.getByLabel('Texto del segmento', { exact: true })
  const original = await area.inputValue()
  await area.fill(original.replace(/bienvenidos/i, 'muy bienvenidos'))
  await panel.getByRole('button', { name: 'Guardar', exact: true }).click()
  await expect(panel.getByText('Versión corregida')).toBeVisible()
  await expect(panel.getByText(/con tiempo estimado \(no medido\)/)).toBeVisible()
  await shot(page, 'p2-05-tiempos-estimados')
  await panel.getByRole('button', { name: 'Realinear con el audio' }).click()
  await expect(panel.getByText(/con tiempo estimado \(no medido\)/)).toHaveCount(0, { timeout: 180_000 })
  await expect(panel.getByRole('button', { name: /^muy$/i })).toBeVisible()
  const id = await projectId(page)
  const st = await api<AnalysisState>(page, `/api/projects/${id}/analysis`)
  const seg = st.transcript!.segments[0]
  expect(st.transcript!.kind).toBe('edited')
  expect(seg.words.every((w) => w.timing === 'aligned')).toBe(true)
  // Persistencia: tras recargar la página la corrección sigue ahí.
  await page.reload()
  await page.getByRole('tab', { name: 'Transcripción' }).click()
  await expect(page.getByRole('tabpanel').getByRole('button', { name: /^muy$/i })).toBeVisible()
})

test('personalizar subtítulos (preset y modo) y ver el cambio en la vista previa', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada')
  await openEditor(page)
  await page.getByRole('tab', { name: 'Edición' }).click()
  await page.getByRole('button', { name: /^Subtítulos/ }).click()
  await page.getByRole('radio', { name: 'Clásico' }).click()
  await expect(page.getByText('Guardado')).toBeVisible()
  const id = await projectId(page)
  await expect
    .poll(async () => (await api<{ mode: string }>(page, `/api/projects/${id}/subtitles/track`)).mode)
    .toBe('classic')
  await page.getByRole('radio', { name: 'Dinámico' }).click()
  await expect(page.getByText('Guardado')).toBeVisible()
  await shot(page, 'p2-06-subtitulos')
})

test('capturar fotograma bajo demanda', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada')
  await openEditor(page)
  await page.locator('video').evaluate((v: HTMLVideoElement) => {
    v.currentTime = 2
  })
  await page.getByRole('tab', { name: 'Análisis' }).click()
  await page.getByRole('button', { name: 'Capturar fotograma actual' }).click()
  await expect(page.getByRole('tabpanel').getByText('Capturas')).toBeVisible()
})

test('exportar video subtitulado y previsualizarlo en el panel', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin voz sintetizada')
  const before = sha256(media('voz_es.mp4'))
  await openEditor(page)
  await page.getByRole('button', { name: 'Exportar', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Exportar video' })
  await expect(dialog.getByText('Integrados')).toBeVisible()
  await dialog.getByRole('button', { name: 'Exportar', exact: true }).click()
  await expect(dialog.getByText('Lista')).toBeVisible({ timeout: 300_000 })
  await shot(page, 'p2-07-exportado')
  await dialog.getByRole('button', { name: 'Ver' }).click()
  const preview = page.locator('video[aria-label="Vista previa de la exportación"]')
  await expect.poll(() => preview.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 30_000 }).toBeGreaterThanOrEqual(2)
  const id = await projectId(page)
  const exports = await api<{ status: string; file_rel: string; width: number; height: number }[]>(page, `/api/projects/${id}/exports`)
  expect(exports[0].status).toBe('succeeded')
  expect([exports[0].width, exports[0].height]).toEqual([720, 1280])
  expect(existsSync(path.join(STORAGE, exports[0].file_rel))).toBe(true)
  expect(sha256(media('voz_es.mp4'))).toBe(before)
})
