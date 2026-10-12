import { expect, test } from '@playwright/test'
import { WRITE } from './helpers'

// Las pruebas de las fases anteriores parten de la biblioteca: se da por hecha la primera
// configuración (la prueba ce2 la recorre de verdad al final).
test('primera configuración marcada como completada', async ({ request }) => {
  const res = await request.post('/api/setup/complete', { headers: WRITE, data: { completed: true } })
  expect(res.ok()).toBeTruthy()
})
