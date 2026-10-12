import { existsSync } from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import type { PlanState, ProjectSummary, ProjectUsage } from '../src/lib/types'
import { api, media, sha256, SHOTS } from './helpers'

// Fase 3: planificación con Claude desde el panel.
// Por defecto usa un CLI de Claude Code SIMULADO (VSA_E2E_FAKE_CLAUDE, sin red): valida la
// interfaz y el flujo. Con VSA_E2E_CLAUDE=1 usa Claude Opus 5.5 real (consume cuota del plan).
test.describe.configure({ mode: 'serial' })

const REAL = process.env.VSA_E2E_CLAUDE === '1'
const FAKE = process.env.VSA_E2E_FAKE_CLAUDE ?? ''
const NAME = 'voz_es'
const WAIT = REAL ? 600_000 : 60_000
const H = { 'X-VSA-Client': '1' }

const shot = async (page: Page, name: string) => {
  await page.waitForTimeout(600)
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) })
}

async function projectId(page: Page) {
  return (await api<ProjectSummary[]>(page, '/api/projects')).find((p) => p.name === NAME)!.id
}

async function plan(page: Page) {
  return api<PlanState>(page, `/api/projects/${await projectId(page)}/plan`)
}

async function waitIdle(page: Page) {
  await expect.poll(async () => (await plan(page)).job, { timeout: WAIT, intervals: [1500] }).toBeNull()
}

async function openPlan(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await page.getByRole('tab', { name: 'Plan IA' }).click()
}

test.beforeAll(async ({ request }) => {
  if (REAL) return
  test.skip(!FAKE || !existsSync(FAKE), 'Falta el CLI simulado (usa «npm run e2e»)')
  const prefs = await (await request.get('/api/claude/settings')).json()
  const res = await request.put('/api/claude/settings', { data: { ...prefs, cli_path: FAKE }, headers: H })
  expect(res.ok()).toBeTruthy()
})

test('Ajustes → Claude: estado real de la conexión y prueba', async ({ page }) => {
  await page.goto('/settings')
  const section = page.locator('#claude')
  await section.scrollIntoViewIfNeeded()
  await expect(section.getByText('Estado de la conexión')).toBeVisible()
  await expect(section.getByText(/claude-opus-5-5/).first()).toBeVisible()
  await expect(section.getByRole('radio', { name: 'Medio' })).toHaveAttribute('data-state', 'on')
  await section.getByRole('button', { name: 'Probar conexión' }).click()
  await expect(section.getByText('Conectado y verificado')).toBeVisible({ timeout: 120_000 })
  await expect(section.getByText('Última prueba real correcta')).toBeVisible()
  await section.screenshot({ path: path.join(SHOTS, 'p3-01-conexion.png') })
})

test('planificar desde el panel: progreso, propuesta, carril de la línea de tiempo y storyboard', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await page.getByRole('button', { name: 'Planificar con IA' }).click()
  await expect(page.getByRole('tab', { name: 'Plan IA' })).toHaveAttribute('data-state', 'active')
  const panel = page.getByRole('tabpanel')
  await panel.getByRole('button', { name: 'Planificar edición con IA' }).click()
  await expect(panel.getByRole('status')).toBeVisible()
  await shot(page, 'p3-02-planificando')
  await waitIdle(page)
  await expect(panel.getByText('En revisión')).toBeVisible()
  await expect(panel.getByText('Propuesta general')).toBeVisible()
  const st = await plan(page)
  const items = st.plan!.document.interventions
  expect(items.length).toBeGreaterThan(0)
  // Carril del plan en la línea de tiempo: seleccionar lleva el reproductor a ese segundo.
  const lane = page.locator('[data-plan-id]')
  await expect(lane).toHaveCount(items.length)
  const target = items[Math.min(1, items.length - 1)]
  await page.locator(`[data-plan-id="${target.id}"]`).click()
  await expect
    .poll(() => page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime))
    .toBeGreaterThan(target.start - 0.05)
  expect(await page.locator('video').first().evaluate((v: HTMLVideoElement) => v.currentTime)).toBeLessThan(target.start + 0.2)
  await expect(panel.getByText('Qué se verá')).toBeVisible()
  await expect(panel.getByText('Por qué (Claude)')).toBeVisible()
  await shot(page, 'p3-03-propuesta')
  await panel.getByRole('button', { name: 'Storyboard' }).click()
  const board = page.getByRole('dialog', { name: 'Storyboard del plan' })
  await expect(board.getByText(/no un render/)).toBeVisible()
  await expect(board.locator('li')).toHaveCount(items.filter((i) => i.status !== 'rejected').length)
  await shot(page, 'p3-04-storyboard')
  await page.keyboard.press('Escape')
})

test('aceptar, rechazar, corregir en lenguaje natural, alternativa, deshacer y rehacer', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  await openPlan(page)
  const panel = page.getByRole('tabpanel')
  let st = await plan(page)
  const [a, b, c] = st.plan!.document.interventions
  test.skip(!c, 'El plan necesita al menos tres intervenciones')
  const card = (id: string) => panel.locator(`#iv-${id}`)
  // Aceptar la primera
  await card(a.id).locator('[role="button"]').first().click()
  await card(a.id).getByRole('button', { name: 'Aceptar', exact: true }).click()
  await expect(card(a.id).getByText('Aceptada').first()).toBeVisible()
  // Rechazar la segunda
  await card(b.id).locator('[role="button"]').first().click()
  await card(b.id).getByRole('button', { name: 'Rechazar', exact: true }).click()
  await expect(card(b.id).getByText('Rechazada').first()).toBeVisible()
  const acceptedBefore = (await plan(page)).plan!.document.interventions.find((i) => i.id === a.id)
  // Corrección en lenguaje natural limitada a la tercera
  await card(c.id).locator('[role="button"]').first().click()
  await card(c.id).getByLabel('Instrucción para esta intervención').fill('Hazla más minimalista')
  await card(c.id).getByRole('button', { name: 'Enviar corrección a Claude' }).click()
  await waitIdle(page)
  st = await plan(page)
  const revised = st.plan!.document.interventions.find((i) => i.id === c.id)!
  expect(revised.origin).toBe('revised')
  expect(revised.revision).toBe(2)
  expect(st.plan!.document.interventions.find((i) => i.id === a.id)).toEqual(acceptedBefore)
  await shot(page, 'p3-05-corregida')
  // Alternativa
  await card(c.id).getByRole('button', { name: 'Alternativa' }).click()
  await waitIdle(page)
  st = await plan(page)
  expect(st.plan!.document.interventions.find((i) => i.id === c.id)!.origin).toBe('alternative')
  const v = st.plan!.current_version
  // Deshacer y rehacer
  await panel.getByRole('button', { name: 'Deshacer' }).click()
  await expect.poll(async () => (await plan(page)).plan!.current_version).toBe(v - 1)
  expect((await plan(page)).plan!.document.interventions.find((i) => i.id === c.id)!.origin).toBe('revised')
  await panel.getByRole('button', { name: 'Rehacer' }).click()
  await expect.poll(async () => (await plan(page)).plan!.current_version).toBe(v)
})

test('aprobar el plan completo y recuperar todo al reabrir', async ({ page }) => {
  test.skip(!existsSync(media('voz_es.mp4')), 'Sin el proyecto de voz de la Fase 2')
  const before = sha256(media('voz_es.mp4'))
  await openPlan(page)
  const panel = page.getByRole('tabpanel')
  await panel.getByRole('button', { name: 'Aceptar pendientes' }).click()
  // Si dos aceptadas chocan, se rechaza la segunda de cada conflicto (decisión del usuario).
  const pid = await projectId(page)
  for (const conflict of (await plan(page)).plan!.document.validation.conflicts ?? []) {
    await page.request.patch(`/api/projects/${pid}/plan/interventions/${conflict.b}`, { data: { status: 'rejected' }, headers: H })
  }
  await page.reload()
  await page.getByRole('tab', { name: 'Plan IA' }).click()
  await page.getByRole('tabpanel').getByRole('button', { name: 'Aprobar plan completo' }).click()
  await expect(page.getByRole('tabpanel').getByText(/Plan aprobado \(v\d+\)/)).toBeVisible()
  await shot(page, 'p3-06-aprobado')
  const approved = await api<{ contract: string; version: number; interventions: { status: string }[] }>(page, `/api/projects/${pid}/plan/approved`)
  expect(approved.contract).toBe('video-studio-ai/edit-plan')
  expect(approved.interventions.every((i) => i.status === 'accepted')).toBe(true)
  // Reabrir: la pestaña, el estado y las decisiones se recuperan.
  await page.goto('/')
  await page.getByRole('button', { name: `Abrir proyecto ${NAME}` }).click()
  await expect(page.getByRole('tab', { name: 'Plan IA' })).toHaveAttribute('data-state', 'active')
  await expect(page.getByRole('tabpanel').getByText('Aprobado').first()).toBeVisible()
  // Consumo del proyecto
  await page.getByRole('tabpanel').getByRole('button', { name: 'Más acciones del plan' }).click()
  await page.getByRole('menuitem', { name: 'Consumo de Claude' }).click()
  const usage = page.getByRole('dialog', { name: 'Consumo de Claude en este proyecto' })
  await expect(usage.getByText('Solicitudes')).toBeVisible()
  const u = await api<ProjectUsage>(page, `/api/projects/${pid}/usage`)
  expect(u.calls).toBeGreaterThanOrEqual(3)
  expect(u.items.every((i) => i.model === 'claude-opus-5-5' && i.effort === 'medium')).toBe(true)
  await shot(page, 'p3-07-consumo')
  expect(sha256(media('voz_es.mp4'))).toBe(before)
})
