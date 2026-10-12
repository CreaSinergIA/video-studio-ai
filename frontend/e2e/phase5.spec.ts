import { existsSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { AnimationsState, ClaudePreferences, EngineStatus, ProjectSummary, SceneState } from '../src/lib/types'
import { api, media, sha256, SHOTS } from './helpers'

// Fase 5: regeneración selectiva de una escena (Claude simulado), comparación y versiones,
// confirmación del presupuesto de solicitudes, copias de seguridad y subtítulos en zona segura.
// Se ejecuta tras la Fase 4.1 (proyecto «voz_es» con plan aprobado y animaciones generadas).
test.describe.configure({ mode: 'serial' })

const NAME = 'voz_es'
const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) })

async function projectId(page: Page) {
  return (await api<ProjectSummary[]>(page, '/api/projects')).find((p) => p.name === NAME)!.id
}

async function open(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await page.getByRole('slider', { name: 'Línea de tiempo' }).waitFor()
}

async function setPrefs(page: Page, patch: Partial<ClaudePreferences>) {
  const prefs = await api<ClaudePreferences>(page, '/api/claude/settings')
  await page.request.put('/api/claude/settings', { data: { ...prefs, ...patch }, headers: { 'X-VSA-Client': '1' } })
}

test.beforeEach(async ({ request }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  const engine = (await (await request.get('/api/animations/engine')).json()) as EngineStatus
  test.skip(!engine.ready, 'El motor de animaciones no está instalado en este equipo')
})

test('modificar una escena desde la línea de tiempo, comparar y usar la nueva versión', async ({ page }) => {
  const before = sha256(media('voz_es.mp4'))
  await open(page)
  const id = await projectId(page)
  const anim = await api<AnimationsState>(page, `/api/projects/${id}/animations`)
  const scene = anim.items.find((i) => i.status === 'ready')!
  const otherClips = Object.fromEntries(anim.items.map((i) => [i.intervention_id, i.render_ms]))
  // Seleccionar la escena en la línea de tiempo: barra de escena con acceso directo.
  await page.locator(`[data-plan-id="${scene.intervention_id}"]`).click()
  const bar = page.getByRole('region', { name: 'Escena seleccionada' })
  await expect(bar).toBeVisible()
  await bar.getByRole('button', { name: 'Abrir escena' }).click()
  const dialog = page.getByRole('dialog', { name: /^Escena/ })
  await expect(dialog.getByText('En uso').first()).toBeVisible()
  await dialog.getByRole('button', { name: 'Utiliza menos texto' }).click()
  await expect(dialog.getByRole('textbox')).toHaveValue('Utiliza menos texto')
  await dialog.getByRole('button', { name: 'Modificar', exact: true }).click()
  await expect(dialog.getByRole('status')).toBeVisible()
  await shot(page, 'p5-01-modificando')
  await expect
    .poll(async () => (await api<SceneState>(page, `/api/projects/${id}/scenes/${scene.intervention_id}`)).job, { timeout: 300_000, intervals: [1500] })
    .toBeNull()
  const st = await api<SceneState>(page, `/api/projects/${id}/scenes/${scene.intervention_id}`)
  const cand = st.versions.find((v) => v.status === 'candidate')!
  expect(cand.preview).not.toBeNull()
  expect(st.versions.find((v) => v.in_use)!.preview?.window).toEqual(cand.preview!.window)
  // Comparación real: dos videos de la misma ventana, reproducidos a la vez.
  await expect(dialog.getByLabel('Vista previa En uso')).toBeVisible()
  await expect(dialog.getByLabel('Vista previa Propuesta')).toBeVisible()
  await dialog.getByRole('button', { name: 'Reproducir ambas' }).click()
  await expect.poll(() => dialog.getByLabel('Vista previa Propuesta').evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 10_000 }).toBeGreaterThan(0.2)
  await dialog.getByText(/Qué cambia respecto a la versión en uso/).click()
  await shot(page, 'p5-02-comparar')
  // Aplicar: nueva versión aprobada del plan; solo se regenera lo necesario.
  const planBefore = (await api<AnimationsState>(page, `/api/projects/${id}/animations`)).approved_version
  await dialog.getByRole('button', { name: 'Usar esta versión' }).first().click()
  await page.getByRole('dialog', { name: `¿Usar la versión ${cand.number}?` }).getByRole('button', { name: 'Usar esta versión' }).click()
  await expect(page.getByText(`Versión ${cand.number} en uso`)).toBeVisible()
  await expect
    .poll(async () => (await api<AnimationsState>(page, `/api/projects/${id}/animations`)).job, { timeout: 300_000, intervals: [1500] })
    .toBeNull()
  const after = await api<AnimationsState>(page, `/api/projects/${id}/animations`)
  expect(after.approved_version).toBeGreaterThan(planBefore!)
  const rerendered = after.items.filter((i) => i.status === 'ready' && !i.reused).map((i) => i.intervention_id)
  const allowed = new Set([scene.intervention_id, ...(cand.impact.affected ?? []).map((a) => a.intervention_id)])
  for (const r of rerendered) expect(allowed.has(r)).toBe(true)
  expect(Object.keys(otherClips).length).toBe(after.items.length)
  // Recuperar la versión anterior (sin Claude: todo sale de la caché).
  const restoredBtn = dialog.getByRole('button', { name: 'Recuperar' }).first()
  await expect(restoredBtn).toBeVisible()
  await restoredBtn.click()
  await page.getByRole('dialog', { name: /^¿Usar la versión/ }).getByRole('button', { name: 'Usar esta versión' }).click()
  await expect
    .poll(async () => (await api<SceneState>(page, `/api/projects/${id}/scenes/${scene.intervention_id}`)).in_use, { timeout: 60_000 })
    .not.toBe(cand.number)
  await shot(page, 'p5-03-versiones')
  await page.keyboard.press('Escape')
  expect(sha256(media('voz_es.mp4'))).toBe(before)
})

test('superar el límite autorizado de solicitudes exige confirmación explícita', async ({ page }) => {
  await open(page)
  const id = await projectId(page)
  const anim = await api<AnimationsState>(page, `/api/projects/${id}/animations`)
  const scene = anim.items.find((i) => i.status === 'ready')!
  await setPrefs(page, { daily_request_limit: 1 })
  try {
    await page.locator(`[data-plan-id="${scene.intervention_id}"]`).click()
    await page.getByRole('region', { name: 'Escena seleccionada' }).getByRole('button', { name: 'Abrir escena' }).click()
    const dialog = page.getByRole('dialog', { name: /^Escena/ })
    await dialog.getByRole('textbox').fill('Haz el título más grande')
    await dialog.getByRole('button', { name: 'Modificar', exact: true }).click()
    const confirm = page.getByRole('dialog', { name: 'Confirmar solicitudes a Claude' })
    await expect(confirm).toBeVisible()
    await expect(confirm.getByText(/Usadas en 24 h/)).toBeVisible()
    await shot(page, 'p5-04-confirmar-presupuesto')
    await confirm.getByRole('button', { name: 'Cancelar' }).click()
    await expect(page.getByText(/no se confirmó el uso adicional/)).toBeVisible()
    const st = await api<SceneState>(page, `/api/projects/${id}/scenes/${scene.intervention_id}`)
    expect(st.job).toBeNull()
    expect(st.versions.some((v) => v.instruction === 'Haz el título más grande')).toBe(false)
  } finally {
    await setPrefs(page, { daily_request_limit: 30 })
  }
})

test('Ajustes → Datos y respaldos: crear una copia verificada', async ({ page }) => {
  await page.goto('/settings#backups')
  const section = page.locator('#backups')
  await expect(section.getByText('Base de datos íntegra')).toBeVisible()
  await section.getByRole('button', { name: 'Crear copia ahora' }).click()
  await expect(page.getByText('Copia creada y verificada')).toBeVisible()
  await expect(section.getByText(/^manual-/).first()).toBeVisible()
  await shot(page, 'p5-05-respaldos')
})

test('subtítulos dentro de la zona segura de la plataforma (opción del usuario)', async ({ page }) => {
  await open(page)
  const id = await projectId(page)
  await page.getByRole('tab', { name: 'Edición' }).click()
  await page.getByRole('button', { name: /^Subtítulos/ }).click()
  const toggle = page.getByRole('switch', { name: 'Dentro de la zona segura' })
  await expect(toggle).toBeVisible()
  await expect(toggle).not.toBeChecked() // nunca se activa sin que el usuario lo pida
  await toggle.click()
  await expect(page.getByText('Guardado')).toBeVisible()
  await expect
    .poll(async () => (await api<{ safe_area?: { status: string } }>(page, `/api/projects/${id}/subtitles/track`)).safe_area?.status, { timeout: 15_000 })
    .not.toBe('off')
  await expect(page.getByText(/Dentro de la zona segura \(|no hay sitio seguro/)).toBeVisible()
  await shot(page, 'p5-06-subtitulos-zona-segura')
  await toggle.click()
  await expect(page.getByText('Guardado')).toBeVisible()
})
