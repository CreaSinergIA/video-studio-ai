// Proceso de render aislado (lo lanza el backend; nunca recibe código, solo especificaciones).
//   node scripts/render.mjs bundle <entry> <publicDir> <outDir>
//   node scripts/render.mjs render <job.json>
// Emite una línea JSON por evento en stdout. SIGTERM cancela el render en curso.
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { bundle } from '@remotion/bundler'
import { makeCancelSignal, openBrowser, renderMedia, selectComposition } from '@remotion/renderer'

// El servidor interno de Remotion (archivos y video fuera de hilo, puertos 3000–3100) escucha
// en todas las interfaces y no ofrece opción para evitarlo. Aquí se limita a la interfaz local:
// el navegador de render lo abre como http://localhost:<puerto>.
const listen = net.Server.prototype.listen
net.Server.prototype.listen = function (...args) {
  const opts = args[0]
  if (opts && typeof opts === 'object' && opts.path === undefined && (opts.host === '0.0.0.0' || opts.host === '::' || opts.host === undefined)) {
    args[0] = { ...opts, host: '127.0.0.1' }
  }
  return listen.apply(this, args)
}

const emit = (o) => process.stdout.write(JSON.stringify(o) + '\n')
const [, , cmd, ...args] = process.argv

async function doBundle(entry, publicDir, outDir) {
  const tmp = `${outDir}.tmp-${process.pid}`
  fs.rmSync(tmp, { recursive: true, force: true })
  await bundle({
    entryPoint: path.resolve(entry),
    publicDir: path.resolve(publicDir),
    outDir: tmp,
    enableCaching: false,
    onProgress: (p) => emit({ type: 'bundle', progress: p / 100 }),
  })
  fs.rmSync(outDir, { recursive: true, force: true })
  fs.renameSync(tmp, outDir)
  emit({ type: 'bundled', outDir })
}

async function doRender(jobPath) {
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'))
  if (!job.browserExecutable || !fs.existsSync(job.browserExecutable)) throw new Error('Falta el navegador de render verificado.')
  const chromiumOptions = { disableWebSecurity: false, ignoreCertificateErrors: false, headless: true }
  const browser = await openBrowser('chrome', {
    browserExecutable: job.browserExecutable,
    chromiumOptions,
    logLevel: 'error',
  })
  let current = null
  const stop = async () => {
    if (current) {
      current.cancel()
      fs.rmSync(current.tmp, { force: true })
    }
    await browser.close({ silent: true }).catch(() => {})
    process.exit(130)
  }
  process.on('SIGTERM', stop)
  process.on('SIGINT', stop)
  try {
    for (const clip of job.clips) {
      const started = Date.now()
      const inputProps = clip.spec
      const tmp = `${clip.out}.partial.mov`
      const { cancelSignal, cancel } = makeCancelSignal()
      current = { cancel, tmp }
      // Un error en un clip (también al preparar su composición) no aborta los demás.
      try {
        const composition = await selectComposition({
          serveUrl: job.serveUrl,
          id: 'Clip',
          inputProps,
          puppeteerInstance: browser,
          browserExecutable: job.browserExecutable,
          chromiumOptions,
          timeoutInMilliseconds: 60000,
          logLevel: 'error',
        })
        emit({ type: 'start', key: clip.key, frames: composition.durationInFrames })
        await renderMedia({
          composition,
          serveUrl: job.serveUrl,
          codec: 'prores',
          proResProfile: '4444',
          pixelFormat: 'yuva444p10le',
          imageFormat: 'png',
          outputLocation: tmp,
          inputProps,
          puppeteerInstance: browser,
          browserExecutable: job.browserExecutable,
          chromiumOptions,
          concurrency: job.concurrency ?? null,
          timeoutInMilliseconds: 60000,
          cancelSignal,
          logLevel: 'error',
          overwrite: true,
          onProgress: ({ progress }) => emit({ type: 'progress', key: clip.key, progress }),
        })
        fs.renameSync(tmp, clip.out)
        emit({ type: 'done', key: clip.key, ms: Date.now() - started })
      } catch (e) {
        fs.rmSync(tmp, { force: true })
        emit({ type: 'error', key: clip.key, message: String(e && e.message ? e.message : e).slice(0, 2000) })
      }
      current = null
    }
  } finally {
    await browser.close({ silent: true }).catch(() => {})
  }
}

try {
  if (cmd === 'bundle') await doBundle(args[0], args[1], args[2])
  else if (cmd === 'render') await doRender(args[0])
  else throw new Error(`Orden desconocida: ${cmd}`)
  process.exit(0)
} catch (e) {
  emit({ type: 'fatal', message: String(e && e.message ? e.message : e).slice(0, 2000) })
  process.exit(1)
}
