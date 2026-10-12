import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { expect, type Page } from '@playwright/test'

export const STORAGE = process.env.VSA_E2E_STORAGE as string
export const MEDIA = process.env.VSA_E2E_MEDIA as string
export const SHOTS = path.resolve(process.env.VSA_E2E_SHOTS ?? 'test-results/screenshots')

export const media = (name: string) => path.join(MEDIA, name)

export function sha256(file: string): string {
  return createHash('sha256').update(readFileSync(file)).digest('hex')
}

/** Simula soltar archivos reales sobre un elemento (drag & drop del sistema). */
export async function dropFiles(page: Page, selector: string, files: string[]) {
  const payload = files.map((file) => ({
    name: path.basename(file),
    type: file.toLowerCase().endsWith('.mov') ? 'video/quicktime' : 'video/mp4',
    b64: readFileSync(file).toString('base64'),
  }))
  const dataTransfer = await page.evaluateHandle((items) => {
    const dt = new DataTransfer()
    for (const item of items) {
      const bytes = Uint8Array.from(atob(item.b64), (c) => c.charCodeAt(0))
      dt.items.add(new File([bytes], item.name, { type: item.type }))
    }
    return dt
  }, payload)
  await page.dispatchEvent(selector, 'dragenter', { dataTransfer })
  await page.dispatchEvent(selector, 'dragover', { dataTransfer })
  await page.dispatchEvent(selector, 'drop', { dataTransfer })
}

/** Importa con el selector del navegador (nunca abre el selector nativo de macOS en pruebas). */
export async function uploadViaBrowser(page: Page, files: string[]) {
  await page.getByRole('button', { name: 'Más opciones de importación' }).click()
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('menuitem', { name: 'Subir desde el navegador' }).click()
  await (await chooser).setFiles(files)
}

export async function waitProjectReady(page: Page, name: string) {
  const card = page.getByRole('button', { name: `Abrir proyecto ${name}` })
  await expect(card).toBeVisible({ timeout: 60_000 })
  await expect(card.getByRole('img', { name: `Miniatura de ${name}` })).toBeVisible({ timeout: 60_000 })
  await expect(card.getByText(/%$|Preparando/)).toHaveCount(0, { timeout: 90_000 })
  return card
}

export async function api<T>(page: Page, url: string): Promise<T> {
  const res = await page.request.get(url)
  expect(res.ok()).toBeTruthy()
  return (await res.json()) as T
}
