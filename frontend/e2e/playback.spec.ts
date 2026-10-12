import { expect, test } from '@playwright/test'
import type { ProjectSummary } from '../src/lib/types'
import { api } from './helpers'

// Reproduce cada proyecto importado por panel.spec.ts en este navegador.
test('todos los videos importados se reproducen', async ({ page, browserName }) => {
  const projects = (await api<ProjectSummary[]>(page, '/api/projects')).filter((p) => p.source)
  expect(projects.length).toBeGreaterThan(0)
  for (const project of projects) {
    await test.step(`${project.name} (${project.source?.video_codec}, ${browserName})`, async () => {
      await page.goto(`/projects/${project.id}`)
      const video = page.locator('video')
      await expect(video).toBeVisible()
      await expect
        .poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState), { timeout: 20_000 })
        .toBeGreaterThanOrEqual(2)
      // Si este navegador no decodifica el códec (p. ej. HEVC en Chromium de pruebas), el panel
      // debe avisar y ofrecer el proxy; tras crearlo, el video tiene que reproducirse.
      const fallback = page.getByRole('button', { name: 'Crear proxy de reproducción' })
      const undecodable = await video.evaluate((v: HTMLVideoElement) => v.videoWidth === 0)
      if (undecodable) {
        await expect(fallback).toBeVisible()
        await fallback.click()
        await expect
          .poll(() => video.evaluate((v: HTMLVideoElement) => v.currentSrc), { timeout: 60_000 })
          .toContain('/proxy')
        await expect
          .poll(() => video.evaluate((v: HTMLVideoElement) => v.videoWidth), { timeout: 20_000 })
          .toBeGreaterThan(0)
      }
      await video.evaluate((v: HTMLVideoElement) => {
        v.muted = true
        return v.play()
      })
      await expect
        .poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 15_000 })
        .toBeGreaterThan(0.3)
      const dims = await video.evaluate((v: HTMLVideoElement) => [v.videoWidth, v.videoHeight])
      const vertical = project.source?.orientation === 'vertical'
      expect(vertical ? dims[1] > dims[0] : dims[0] >= dims[1], `${project.name}: ${dims.join('x')} (${project.source?.orientation})`).toBe(true)
    })
  }
})

test('el reproductor del panel emite audio real (reproducir, pausar, volumen, silencio)', async ({ page, browserName }) => {
  // Proyecto con un tono senoidal estable (medición determinista; el ruido aleatorio no lo es).
  const withAudio = (await api<ProjectSummary[]>(page, '/api/projects')).find(
    (p) => p.source?.has_audio && p.source.browser_playable && /reel_vertical|Entrevista/i.test(p.name),
  )
  expect(withAudio, 'un proyecto con audio reproducible').toBeTruthy()
  await page.goto(`/projects/${withAudio!.id}`)
  const video = page.locator('video').first()
  await video.evaluate((el: HTMLVideoElement) => new Promise((r) => (el.readyState >= 2 ? r(null) : el.addEventListener('loadeddata', () => r(null), { once: true }))))
  // Medidor sobre la salida del elemento (después de volumen y silencio).
  await video.evaluate((el: HTMLVideoElement) => {
    const w = window as unknown as { __lv: number[]; __raw: number[]; __ctx: AudioContext; __stale: number }
    const ctx = new AudioContext()
    const an = ctx.createAnalyser()
    an.fftSize = 2048
    ctx.createMediaElementSource(el).connect(an)
    an.connect(ctx.destination)
    const buf = new Float32Array(an.fftSize)
    const prev = new Float32Array(an.fftSize)
    w.__lv = []
    w.__raw = []
    w.__stale = 0
    w.__ctx = ctx
    setInterval(() => {
      an.getFloatTimeDomainData(buf)
      // Fase 5: WebKit puede dejar de entregar bloques nuevos al analizador cuando el elemento
      // se pausa y devolver el último una y otra vez. Un bloque idéntico al anterior no es
      // sonido nuevo: cuenta como silencio (y se registra para el diagnóstico).
      let same = true
      for (let i = 0; i < buf.length; i++) if (buf[i] !== prev[i]) { same = false; break }
      prev.set(buf)
      let s = 0
      for (const x of buf) s += x * x
      const level = 10 * Math.log10(s / buf.length + 1e-12)
      w.__raw.push(level)
      if (same) {
        w.__stale++
        w.__lv.push(-120)
        return
      }
      w.__lv.push(level)
    }, 50)
  })
  // Nivel típico (mediana de ventanas de 50 ms) tras dejar estabilizarse el cambio.
  const peak = async (ms = 1200) => {
    await page.waitForTimeout(300)
    await page.evaluate(() => ((window as unknown as { __lv: number[] }).__lv = []))
    await page.waitForTimeout(ms)
    return page.evaluate(() => {
      const v = [...(window as unknown as { __lv: number[] }).__lv].sort((a, b) => a - b)
      return v[Math.floor(v.length / 2)]
    })
  }
  // Punto de partida conocido: el volumen se recuerda entre sesiones (la prueba debe poder
  // repetirse sobre el mismo proyecto).
  await video.evaluate((el: HTMLVideoElement) => {
    el.volume = 1
    el.muted = false
  })
  await page.getByRole('button', { name: 'Reproducir' }).first().click() // gesto real del usuario
  await page.evaluate(() => (window as unknown as { __ctx: AudioContext }).__ctx.resume())
  expect(await video.evaluate((el: HTMLVideoElement) => el.muted)).toBe(false)
  const playing = await peak()
  expect(playing).toBeGreaterThan(-40)
  await video.evaluate((el: HTMLVideoElement) => (el.volume = 0.2))
  const quieter = await peak()
  expect(await video.evaluate((el: HTMLVideoElement) => el.volume)).toBeCloseTo(0.2)
  // WebKit mide después del volumen del elemento; Chromium entrega al analizador la señal
  // previa al volumen (limitación del motor), así que allí solo se comprueba la propiedad.
  if (browserName === 'webkit') expect(quieter).toBeLessThan(playing - 6)
  else expect(quieter).toBeGreaterThan(-60)
  await page.keyboard.press('k') // pausa
  // Comportamiento del reproductor: realmente pausado y el tiempo no avanza.
  await expect.poll(() => video.evaluate((el: HTMLVideoElement) => el.paused)).toBe(true)
  const t0 = await video.evaluate((el: HTMLVideoElement) => el.currentTime)
  await page.waitForTimeout(300)
  expect(await video.evaluate((el: HTMLVideoElement) => el.currentTime)).toBe(t0)
  // Y en la salida de audio no hay sonido nuevo.
  await page.evaluate(() => {
    const w = window as unknown as { __raw: number[]; __stale: number }
    w.__raw = []
    w.__stale = 0
  })
  const silent = await peak()
  const diag = await page.evaluate(() => {
    const w = window as unknown as { __raw: number[]; __stale: number }
    const v = [...w.__raw].sort((a, b) => a - b)
    return { rawMedian: v[Math.floor(v.length / 2)], stale: w.__stale, reads: w.__raw.length }
  })
  // Diagnóstico de la intermitencia (Fase 5): con el criterio antiguo (sin descartar bloques
  // repetidos) esta medición habría fallado si rawMedian > −60 con el video ya pausado.
  test.info().annotations.push({ type: 'silencio', description: JSON.stringify({ silent, ...diag }) })
  expect(silent).toBeLessThan(-60)
})
