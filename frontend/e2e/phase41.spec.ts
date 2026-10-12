import { existsSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { AnimationLayout, ProjectSummary } from '../src/lib/types'
import { api, media, SHOTS } from './helpers'

// Fase 4.1: destino (zonas seguras de redes sociales), guías del reproductor y presencia de los
// efectos de sonido. Se ejecuta tras la Fase 4 (proyecto «voz_es» con plan aprobado).
test.describe.configure({ mode: 'serial' })

const NAME = 'voz_es'

async function projectId(page: Page) {
  return (await api<ProjectSummary[]>(page, '/api/projects')).find((p) => p.name === NAME)!.id
}

async function openEdition(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await page.getByRole('tab', { name: 'Edición' }).click()
}

test('destino por defecto Universal; cambiar a TikTok y ver las zonas en el reproductor', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  await openEdition(page)
  const id = await projectId(page)
  const project = await api<{ config: { delivery: { platform: string } } }>(page, `/api/projects/${id}`)
  expect(project.config.delivery.platform).toBe('universal')
  await page.getByRole('button', { name: /^Destino/ }).click()
  await page.getByRole('combobox', { name: 'Red social de destino' }).click()
  await page.getByRole('option', { name: 'TikTok', exact: true }).click()
  await expect(page.getByText('Guardado')).toBeVisible()
  await expect
    .poll(async () => (await api<{ config: { delivery: { platform: string } } }>(page, `/api/projects/${id}`)).config.delivery.platform)
    .toBe('tiktok')
  // Guías: solo en el panel; muestran la interfaz de TikTok y las regiones calculadas.
  await page.getByRole('button', { name: 'Mostrar zonas seguras' }).click()
  const guides = page.getByTestId('safe-zone-guides')
  await expect(guides).toBeVisible()
  await expect(guides.getByText('Para ti')).toBeVisible()
  // Además de la interfaz: franja de subtítulos calculada y región de la animación activa.
  await expect(guides.getByText('Subtítulos')).toBeVisible()
  const first = (await api<AnimationLayout>(page, `/api/projects/${id}/animations/layout`)).items.find((i) => i.mode === 'overlay')
  if (first) {
    await page.locator('video').first().evaluate((v: HTMLVideoElement, t) => { v.pause(); v.currentTime = t }, (first.start + first.end) / 2)
    await expect(guides.getByText(first.template)).toBeVisible()
  }
  const layout = await api<AnimationLayout>(page, `/api/projects/${id}/animations/layout`)
  expect(layout.platform?.id).toBe('tiktok')
  expect(layout.applies).toBe(true)
  for (const it of layout.items.filter((i) => i.mode === 'overlay' && !i.template.endsWith('.highlight'))) {
    for (const z of layout.platform!.zones) {
      const ox = Math.min(it.region.x + it.region.w, z.x + z.w) - Math.max(it.region.x, z.x)
      const oy = Math.min(it.region.y + it.region.h, z.y + z.h) - Math.max(it.region.y, z.y)
      // Ninguna animación informativa en la interfaz sin aviso explícito.
      if (ox > 0.01 && oy > 0.01) expect(it.warnings.length).toBeGreaterThan(0)
    }
  }
  await page.screenshot({ path: path.join(SHOTS, 'p41-01-zonas-tiktok.png') })
  await page.getByRole('button', { name: 'Ocultar zonas seguras' }).click()
  await expect(guides).toHaveCount(0)
  // Volver a Universal (valor por defecto).
  await page.getByRole('combobox', { name: 'Red social de destino' }).click()
  await page.getByRole('option', { name: /^Universal/ }).click()
  await expect
    .poll(async () => (await api<{ config: { delivery: { platform: string } } }>(page, `/api/projects/${id}`)).config.delivery.platform)
    .toBe('universal')
})

test('presencia de los efectos de sonido: Suave, Equilibrada e Intensa', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  await openEdition(page)
  const id = await projectId(page)
  await page.getByRole('button', { name: /^Audio/ }).click()
  await expect(page.getByRole('radio', { name: 'Equilibrada' })).toHaveAttribute('data-state', 'on')
  await page.getByRole('radio', { name: 'Intensa' }).click()
  await expect
    .poll(async () => (await api<{ config: { audio: { sfx_intensity: string } } }>(page, `/api/projects/${id}`)).config.audio.sfx_intensity)
    .toBe('strong')
  await page.screenshot({ path: path.join(SHOTS, 'p41-02-audio.png') })
  await page.getByRole('radio', { name: 'Equilibrada' }).click()
  await expect
    .poll(async () => (await api<{ config: { audio: { sfx_intensity: string } } }>(page, `/api/projects/${id}`)).config.audio.sfx_intensity)
    .toBe('balanced')
})
