import { defineConfig, devices } from '@playwright/test'
import { E2E_TOKEN } from './e2e/helpers'

// Ejecutar con: npm run e2e (prepara datos aislados en e2e/run-e2e.sh)
const PORT = Number(process.env.VSA_E2E_PORT ?? 8799)
const HOME = process.env.VSA_E2E_HOME
if (!HOME) throw new Error('Usa «npm run e2e» (define VSA_E2E_HOME, VSA_E2E_STORAGE y VSA_E2E_MEDIA).')

const viewport = { width: 1512, height: 945 }
const FAKE_API = process.env.VSA_E2E_FAKE_API

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [['list']],
  outputDir: './test-results',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    extraHTTPHeaders: { 'x-vsa-token': E2E_TOKEN },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport,
  },
  projects: [
    // Community Edition: la primera configuración se da por hecha (la prueba ce2 la recorre).
    { name: 'ce-setup', testMatch: /ce-setup\.ts/ },
    { name: 'webkit', testMatch: /panel\.spec\.ts/, dependencies: ['ce-setup'], use: { ...devices['Desktop Safari'], viewport } },
    { name: 'playback-webkit', testMatch: /playback\.spec\.ts/, dependencies: ['webkit'], use: { ...devices['Desktop Safari'], viewport } },
    { name: 'playback-chromium', testMatch: /playback\.spec\.ts/, dependencies: ['webkit'], use: { ...devices['Desktop Chrome'], viewport } },
    { name: 'fase2-webkit', testMatch: /phase2\.spec\.ts/, dependencies: ['webkit'], timeout: 600_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'real-video', testMatch: /real-video\.spec\.ts/, dependencies: ['fase2-webkit'], timeout: 900_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase3-webkit', testMatch: /phase3\.spec\.ts/, dependencies: ['fase2-webkit'], timeout: 1_200_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase4-webkit', testMatch: /phase4\.spec\.ts/, dependencies: ['fase3-webkit'], timeout: 1_200_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase41-webkit', testMatch: /phase41\.spec\.ts/, dependencies: ['fase4-webkit'], timeout: 600_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase5-webkit', testMatch: /phase5\.spec\.ts/, dependencies: ['fase41-webkit'], timeout: 900_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'ce2-chromium', testMatch: /ce2\.spec\.ts/, dependencies: ['fase5-webkit'], timeout: 300_000, use: { ...devices['Desktop Chrome'], viewport } },
  ],
  webServer: {
    command: '.venv/bin/python run.py',
    cwd: '../backend',
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    stdout: 'ignore',
    stderr: 'pipe',
    env: {
      VSA_PORT: String(PORT),
      VSA_HOME: HOME,
      // Entorno de pruebas marcado: nunca puede abrir el directorio de datos del usuario.
      VSA_ENV: 'test',
      VSA_SESSION_TOKEN: E2E_TOKEN,
      // API de Anthropic simulada (sin red ni cargos) para el flujo de la clave propia.
      ...(FAKE_API ? { VSA_TEST_ANTHROPIC_BASE_URL: FAKE_API } : {}),
      // Modelos de transcripción ya descargados (evita repetir 1,6 GB en cada ejecución).
      ...(process.env.VSA_E2E_MODELS ? { VSA_MODELS_DIR: process.env.VSA_E2E_MODELS } : {}),
      // Frontend compilado para las pruebas (no reemplaza el que sirve la app en uso).
      ...(process.env.VSA_E2E_DIST ? { VSA_FRONTEND_DIST: process.env.VSA_E2E_DIST } : {}),
    },
  },
})
