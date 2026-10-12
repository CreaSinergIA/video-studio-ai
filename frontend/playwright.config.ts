import { defineConfig, devices } from '@playwright/test'

// Ejecutar con: npm run e2e (prepara datos aislados en e2e/run-e2e.sh)
const PORT = Number(process.env.VSA_E2E_PORT ?? 8799)
const HOME = process.env.VSA_E2E_HOME
if (!HOME) throw new Error('Usa «npm run e2e» (define VSA_E2E_HOME, VSA_E2E_STORAGE y VSA_E2E_MEDIA).')

const viewport = { width: 1512, height: 945 }

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
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    viewport,
  },
  projects: [
    { name: 'webkit', testMatch: /panel\.spec\.ts/, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'playback-webkit', testMatch: /playback\.spec\.ts/, dependencies: ['webkit'], use: { ...devices['Desktop Safari'], viewport } },
    { name: 'playback-chromium', testMatch: /playback\.spec\.ts/, dependencies: ['webkit'], use: { ...devices['Desktop Chrome'], viewport } },
    { name: 'fase2-webkit', testMatch: /phase2\.spec\.ts/, dependencies: ['webkit'], timeout: 600_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'real-video', testMatch: /real-video\.spec\.ts/, dependencies: ['fase2-webkit'], timeout: 900_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase3-webkit', testMatch: /phase3\.spec\.ts/, dependencies: ['fase2-webkit'], timeout: 1_200_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase4-webkit', testMatch: /phase4\.spec\.ts/, dependencies: ['fase3-webkit'], timeout: 1_200_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase41-webkit', testMatch: /phase41\.spec\.ts/, dependencies: ['fase4-webkit'], timeout: 600_000, use: { ...devices['Desktop Safari'], viewport } },
    { name: 'fase5-webkit', testMatch: /phase5\.spec\.ts/, dependencies: ['fase41-webkit'], timeout: 900_000, use: { ...devices['Desktop Safari'], viewport } },
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
      // Modelos de transcripción ya descargados (evita repetir 1,6 GB en cada ejecución).
      ...(process.env.VSA_E2E_MODELS ? { VSA_MODELS_DIR: process.env.VSA_E2E_MODELS } : {}),
      // Frontend compilado para las pruebas (no reemplaza el que sirve la app en uso).
      ...(process.env.VSA_E2E_DIST ? { VSA_FRONTEND_DIST: process.env.VSA_E2E_DIST } : {}),
    },
  },
})
