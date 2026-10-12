import { existsSync, readFileSync, renameSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { ProjectDetail, ProjectSummary } from '../src/lib/types'
import { api, dropFiles, media, sha256, SHOTS, STORAGE, uploadViaBrowser, waitProjectReady } from './helpers'

test.describe.configure({ mode: 'serial' })

const SOURCES = [
  'reel_vertical.mp4',
  'Entrevista horizontal.mp4',
  'iPhone vertical.MOV',
  'hevc_60fps.mov',
  'master_prores.mov',
]
const originalHashes = new Map<string, string>()

const shot = async (page: Page, name: string) => {
  await page.waitForTimeout(700) // dejar terminar las animaciones de entrada
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

async function openProject(page: Page, name: string) {
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${name}` }).click()
  await expect(page).toHaveURL(/\/projects\/prj_/)
  await expect(page.getByRole('button', { name: /^Renombrar proyecto/ })).toBeVisible()
}

async function videoState(page: Page) {
  return page.locator('video').evaluate((v: HTMLVideoElement) => ({
    currentTime: v.currentTime,
    duration: v.duration,
    paused: v.paused,
    muted: v.muted,
    readyState: v.readyState,
    src: v.currentSrc,
    videoWidth: v.videoWidth,
    videoHeight: v.videoHeight,
  }))
}

test.beforeAll(() => {
  for (const name of SOURCES) originalHashes.set(name, sha256(media(name)))
})

test('bienvenida: configurar el almacenamiento desde el panel', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Bienvenido a Video Studio AI' })).toBeVisible()
  await shot(page, '01-bienvenida')
  await page.getByLabel('Ruta de la carpeta de almacenamiento').fill(STORAGE)
  await expect(page.getByText('Se creará esta carpeta')).toBeVisible()
  await page.getByRole('button', { name: 'Empezar' }).click()
  await expect(page.getByRole('heading', { name: 'Biblioteca' })).toBeVisible()
  await expect(page.getByText('Arrastra tu primer video aquí')).toBeVisible()
  expect(existsSync(path.join(STORAGE, '.videostudio.json'))).toBe(true)
  await shot(page, '02-biblioteca-vacia')
})

test('importar arrastrando un MP4 vertical', async ({ page }) => {
  await page.goto('/')
  await dropFiles(page, 'main h2', [media('reel_vertical.mp4')])
  await expect(page.getByText('Importaciones')).toBeVisible()
  const card = await waitProjectReady(page, 'reel_vertical')
  await expect(card.getByText('Vertical', { exact: true })).toBeVisible()
  await expect(card.getByText(/1080×1920/)).toBeVisible()
})

test('importar con el selector: MP4 horizontal, MOV rotado, HEVC 60 fps, ProRes y un archivo falso', async ({ page }) => {
  await page.goto('/')
  await uploadViaBrowser(page, [
    media('Entrevista horizontal.mp4'),
    media('iPhone vertical.MOV'),
    media('hevc_60fps.mov'),
    media('master_prores.mov'),
    media('no-es-video.mp4'),
  ])
  await expect(page.getByText('No se pudo importar «no-es-video.mp4»')).toBeVisible({ timeout: 60_000 })
  for (const name of ['Entrevista horizontal', 'iPhone vertical', 'hevc_60fps', 'master_prores']) {
    await waitProjectReady(page, name)
  }
  const iphone = page.getByRole('button', { name: 'Abrir proyecto iPhone vertical' })
  await expect(iphone.getByText('Vertical', { exact: true })).toBeVisible()
  const horizontal = page.getByRole('button', { name: 'Abrir proyecto Entrevista horizontal' })
  await expect(horizontal.getByText('Horizontal', { exact: true })).toBeVisible()
  const projects = await api<ProjectSummary[]>(page, '/api/projects')
  expect(projects).toHaveLength(5)
  await page.mouse.move(0, 0)
  await shot(page, '03-biblioteca')
})

test('duplicados: se detectan antes de subir y se pueden omitir', async ({ page }) => {
  await page.goto('/')
  await dropFiles(page, 'main h1', [media('reel_vertical.mp4')])
  await expect(page.getByRole('heading', { name: 'Este video ya está en tu biblioteca' })).toBeVisible()
  await shot(page, '04-duplicado')
  await page.getByRole('button', { name: 'Omitir' }).click()
  await expect(page.getByText('Omitido: ya estaba importado.')).toBeVisible()
  expect(await api<ProjectSummary[]>(page, '/api/projects')).toHaveLength(5)
})

test('vista de lista y búsqueda', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('radio', { name: 'Lista' }).click()
  await expect(page.getByRole('table', { name: 'Proyectos' })).toBeVisible()
  await page.getByLabel('Buscar proyectos').fill('prores')
  await expect(page.getByRole('button', { name: 'Abrir master_prores' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Abrir reel_vertical' })).toHaveCount(0)
  await shot(page, '05-lista')
  await page.getByRole('radio', { name: 'Cuadrícula' }).click()
})

test('editor vertical: reproducción, controles, línea de tiempo y metadatos', async ({ page }) => {
  await openProject(page, 'reel_vertical')
  const video = page.locator('video')
  await expect(video).toBeVisible()
  await expect.poll(async () => (await videoState(page)).readyState, { timeout: 20_000 }).toBeGreaterThanOrEqual(1)
  const box = await video.boundingBox()
  expect(box && box.height > box.width).toBe(true)

  await page.getByRole('button', { name: 'Reproducir' }).first().click()
  await expect.poll(async () => (await videoState(page)).currentTime, { timeout: 15_000 }).toBeGreaterThan(0.6)
  await page.keyboard.press('k')
  await expect.poll(async () => (await videoState(page)).paused).toBe(true)

  await page.getByRole('button', { name: 'Silenciar' }).click()
  expect((await videoState(page)).muted).toBe(true)
  await page.getByRole('button', { name: 'Activar sonido' }).click()
  expect((await videoState(page)).muted).toBe(false)

  const timeline = page.getByRole('slider', { name: 'Línea de tiempo' })
  const tb = await timeline.boundingBox()
  if (!tb) throw new Error('sin línea de tiempo')
  await page.mouse.click(tb.x + tb.width * 0.75, tb.y + tb.height / 2)
  await expect.poll(async () => (await videoState(page)).currentTime).toBeGreaterThan(5.3)
  expect((await videoState(page)).currentTime).toBeLessThan(6.7)
  await expect(page.getByRole('img', { name: 'Forma de onda del audio' })).toBeVisible()

  await page.getByRole('button', { name: 'Pantalla completa' }).click()
  await expect.soft(page.getByRole('button', { name: 'Salir de pantalla completa' })).toBeVisible({ timeout: 3_000 })
  if (await page.evaluate(() => Boolean(document.fullscreenElement))) await page.keyboard.press('f')

  await page.getByRole('tab', { name: 'Archivo' }).click()
  const panel = page.getByRole('tabpanel')
  await expect(panel.getByText('1080×1920')).toBeVisible()
  await expect(panel.getByText('H.264').first()).toBeVisible()
  await expect(panel.getByText('AAC').first()).toBeVisible()
  await expect(panel.getByText('30 fps').first()).toBeVisible()
  await shot(page, '06-editor-vertical')
})

test('editor horizontal: ajustes de edición persistentes y preset nuevo', async ({ page }) => {
  await openProject(page, 'Entrevista horizontal')
  const box = await page.locator('video').boundingBox()
  expect(box && box.width > box.height).toBe(true)
  await page.getByRole('tab', { name: 'Edición' }).click()
  await page.getByRole('button', { name: /^Muestra Minimal Motion/ }).click()
  await expect(page.getByText('Guardado')).toBeVisible()
  await page.getByRole('button', { name: /^Subtítulos/ }).click()
  await page.getByRole('switch', { name: 'Mayúsculas' }).click()
  await expect(page.getByText('Guardando…')).toBeVisible()
  await expect(page.getByText('Guardado')).toBeVisible()
  await page.getByRole('button', { name: 'Mostrar muestra de estilo de subtítulos' }).click()
  await expect(page.getByText('Muestra de estilo · texto de ejemplo')).toBeVisible()
  await shot(page, '07-editor-horizontal-ajustes')

  await page.reload()
  await expect(page.getByRole('button', { name: /^Muestra Minimal Motion/ })).toHaveAttribute('aria-pressed', 'true')
  const id = page.url().split('/').pop() as string
  const project = await api<ProjectDetail>(page, `/api/projects/${id}`)
  expect(project.config.style.id).toBe('minimal_motion')
  expect(project.config.subtitles.uppercase).toBe(true)

  await page.getByRole('button', { name: 'Guardar como preset' }).click()
  await page.getByLabel('Nombre').fill('Mi preset E2E')
  await page.getByRole('button', { name: 'Guardar preset' }).click()
  await expect(page.getByText('Preset «Mi preset E2E» guardado')).toBeVisible()
})

test('renombrar en línea y persistencia en el manifiesto', async ({ page }) => {
  await openProject(page, 'Entrevista horizontal')
  await page.getByRole('button', { name: /^Renombrar proyecto/ }).click()
  const input = page.getByLabel('Nombre del proyecto')
  await input.fill('Entrevista final')
  await input.press('Enter')
  await expect(page.getByRole('heading', { name: 'Entrevista final' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Entrevista final' })).toBeVisible()
  const id = page.url().split('/').pop() as string
  const project = await api<ProjectDetail>(page, `/api/projects/${id}`)
  const manifest = JSON.parse(readFileSync(path.join(STORAGE, project.dir_rel, 'project.json'), 'utf8'))
  expect(manifest.name).toBe('Entrevista final')
})

test('ProRes: se reproduce mediante proxy H.264', async ({ page }) => {
  await openProject(page, 'master_prores')
  await expect.poll(async () => (await videoState(page)).src, { timeout: 20_000 }).toContain('/proxy')
  await page.getByRole('button', { name: 'Reproducir' }).first().click()
  await expect.poll(async () => (await videoState(page)).currentTime, { timeout: 15_000 }).toBeGreaterThan(0.4)
  await page.getByRole('tab', { name: 'Archivo' }).click()
  await expect(page.getByRole('tabpanel').getByText(/Proxy H\.264/)).toBeVisible()
})

test('proyecto vacío: crear e importar dentro (copia intencional de un duplicado)', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Nuevo proyecto' }).click()
  await page.getByLabel('Nombre').fill('Proyecto desde cero')
  await page.getByRole('button', { name: 'Crear proyecto' }).click()
  await expect(page.getByRole('heading', { name: 'Proyecto desde cero' })).toBeVisible()
  await expect(page.getByText('Importa el video de este proyecto')).toBeVisible()
  await dropFiles(page, 'main h2', [media('hevc_60fps.mov')])
  await expect(page.getByRole('heading', { name: 'Este video ya está en tu biblioteca' })).toBeVisible()
  await page.getByRole('button', { name: 'Importar una copia' }).click()
  await expect(page.locator('video')).toBeVisible({ timeout: 60_000 })
  await expect.poll(async () => (await videoState(page)).videoHeight, { timeout: 20_000 }).toBe(1920)
})

test('ajustes: presets, tema y entorno', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: 'Presets de edición' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Mi preset E2E' })).toBeVisible()
  await page.getByRole('button', { name: 'Acciones de Mi preset E2E' }).click()
  await page.getByRole('menuitem', { name: 'Usar por defecto' }).click()
  await expect(page.getByText('«Mi preset E2E» es ahora el predeterminado')).toBeVisible()

  await page.getByRole('radio', { name: 'Claro' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  await page.locator('#presets').scrollIntoViewIfNeeded()
  await shot(page, '08-ajustes-claro')
  await page.getByRole('radio', { name: 'Oscuro' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

  await page.locator('#environment').scrollIntoViewIfNeeded()
  await expect(page.getByText('Director creativo (Claude Opus 5.5)')).toBeVisible()
  // Fase 5: capacidades del desarrollo inicial operativas (sin «próximas fases» simuladas).
  await expect(page.getByText('Regeneración selectiva y versiones de escena')).toBeVisible()
  await expect(page.getByText('Copias de seguridad verificadas')).toBeVisible()
  await page.locator('#storage').scrollIntoViewIfNeeded()
  await expect(page.getByText('Conectado')).toBeVisible()
  await shot(page, '09-ajustes')
})

test('almacenamiento desconectado: aviso sin corrupción y reconexión', async ({ page }) => {
  const hidden = `${STORAGE}-desconectado`
  renameSync(STORAGE, hidden)
  try {
    await page.goto('/')
    await expect(page.getByText('Almacenamiento no disponible.')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('Disco desconectado').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Importar video' })).toBeDisabled()
    await shot(page, '10-desconectado')
    expect(existsSync(STORAGE)).toBe(false)
  } finally {
    renameSync(hidden, STORAGE)
  }
  await page.getByRole('button', { name: 'Reintentar' }).click()
  await expect(page.getByText('Almacenamiento no disponible.')).toHaveCount(0, { timeout: 15_000 })
  await waitProjectReady(page, 'reel_vertical')
})

test('eliminar proyecto con confirmación explícita', async ({ page }) => {
  const projects = await api<ProjectSummary[]>(page, '/api/projects')
  const target = projects.find((p) => p.name === 'iPhone vertical') as ProjectSummary
  const dir = path.join(STORAGE, target.dir_rel)
  expect(existsSync(dir)).toBe(true)
  await page.goto('/')
  const card = page.getByRole('button', { name: 'Abrir proyecto iPhone vertical' })
  await card.hover()
  await page.getByRole('button', { name: 'Acciones de iPhone vertical' }).click()
  await page.getByRole('menuitem', { name: 'Eliminar…' }).click()
  const confirm = page.getByRole('button', { name: 'Eliminar definitivamente' })
  await expect(confirm).toBeDisabled()
  await shot(page, '11-eliminar')
  await page.getByRole('checkbox').check()
  await confirm.click()
  await expect(page.getByText('Proyecto y archivos eliminados.')).toBeVisible()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(card).toHaveCount(0)
  expect(existsSync(dir)).toBe(false)
  expect(existsSync(path.join(STORAGE, '.videostudio.json'))).toBe(true)
})

test('los originales permanecen intactos', async ({ page }) => {
  const projects = await api<ProjectSummary[]>(page, '/api/projects')
  for (const name of SOURCES) {
    expect(sha256(media(name)), `origen ${name} modificado`).toBe(originalHashes.get(name))
  }
  for (const p of projects) {
    if (!p.source) continue
    const stored = path.join(STORAGE, p.source.file_rel)
    expect(sha256(stored), `copia de ${p.name}`).toBe(p.source.sha256)
    const original = SOURCES.find((s) => s === p.source?.original_filename)
    if (original) expect(p.source.sha256).toBe(originalHashes.get(original))
  }
})
