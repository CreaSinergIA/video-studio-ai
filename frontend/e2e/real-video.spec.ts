import { existsSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import type { AnalysisState, ProjectSummary } from '../src/lib/types'
import { api, sha256, SHOTS, uploadViaBrowser, waitProjectReady } from './helpers'

// Validación de extremo a extremo con un video real autorizado por el usuario.
// Solo se ejecuta si se indica la ruta en VSA_E2E_REAL_VIDEO (se importa una copia; el
// original solo se lee y se verifica su huella al final).
const REAL = process.env.VSA_E2E_REAL_VIDEO ?? ''

test('video real: importar, analizar, revisar, subtitular y exportar desde el panel', async ({ page }) => {
  test.skip(!REAL || !existsSync(REAL), 'Define VSA_E2E_REAL_VIDEO con un video autorizado')
  const before = sha256(REAL)
  const name = path.basename(REAL).replace(/\.[^.]+$/, '')
  await page.goto('/')
  await uploadViaBrowser(page, [REAL])
  await waitProjectReady(page, name)
  await page.getByRole('button', { name: `Abrir proyecto ${name}` }).click()
  await page.getByRole('button', { name: 'Analizar video' }).click()
  const id = (await api<ProjectSummary[]>(page, '/api/projects')).find((p) => p.name === name)!.id
  await expect
    .poll(async () => {
      const st = await api<AnalysisState>(page, `/api/projects/${id}/analysis`)
      return Boolean(st.transcript && st.visual)
    }, { timeout: 600_000, intervals: [3000] })
    .toBe(true)
  const st = await api<AnalysisState>(page, `/api/projects/${id}/analysis`)
  expect(st.transcript!.language).toBe('es')
  expect(st.transcript!.segments.length).toBeGreaterThan(5)
  expect(st.visual!.scenes.some((s) => s.labels.faces === 'single' || s.labels.faces === 'multiple')).toBe(true)
  // Subtítulos automáticos: bajo el rostro detectado.
  const track = await api<{ height: number; blocks: { top: number; position_source: string }[] }>(page, `/api/projects/${id}/subtitles/track`)
  expect(track.blocks.every((b) => b.position_source === 'auto-faces')).toBe(true)
  await page.locator('video').evaluate((v: HTMLVideoElement) => {
    v.currentTime = 10.5
  })
  await page.getByRole('tab', { name: 'Transcripción' }).click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: path.join(SHOTS, 'real-01-editor.png') })
  await page.getByRole('tab', { name: 'Análisis' }).click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: path.join(SHOTS, 'real-02-analisis.png') })
  await page.getByRole('button', { name: 'Exportar', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Exportar video' })
  await dialog.getByRole('radio', { name: '1080p' }).click()
  await dialog.getByRole('button', { name: 'Exportar', exact: true }).click()
  await expect(dialog.getByText('Lista').first()).toBeVisible({ timeout: 600_000 })
  await page.screenshot({ path: path.join(SHOTS, 'real-03-exportado.png') })
  expect(sha256(REAL)).toBe(before)
})
