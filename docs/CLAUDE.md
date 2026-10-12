# Conexión con Claude

Video Studio AI usa **Claude Opus 5.5** de Anthropic como director creativo: analiza la transcripción y unos pocos fotogramas reducidos, y propone el plan de edición y la dirección de las animaciones, que tú revisas y apruebas.

## Tu propia clave de API (mecanismo oficial)
- Cada persona usa **su propia clave** de la Consola de Claude: https://platform.claude.com/settings/keys
- Se configura en el panel: **primera configuración** o **Ajustes → Claude**. Ahí puedes:
  - **guardar** la clave;
  - **comprobarla sin coste** («Comprobar»): consulta la API de modelos de Anthropic para verificar la clave y el acceso a Opus 5.5, sin enviar ninguna solicitud al modelo;
  - **probar la conexión** con una solicitud real mínima (sin datos tuyos; coste mínimo);
  - **cambiarla** o **eliminarla** (con confirmación).
- **Dónde se guarda:** en el llavero del sistema, en un servicio propio de esta edición (`VideoStudioAI-Community`):
  - macOS: Llavero de inicio de sesión;
  - Windows: Administrador de credenciales de Windows (credencial genérica cifrada para tu cuenta);
  - nunca en el navegador, la base de datos, los registros ni los archivos del proyecto.
- El repositorio **no incluye ninguna clave** ni configuración de Claude.

## Costes
- **Video Studio AI es gratuito; Claude no.** Las solicitudes se facturan en **tu** cuenta de Anthropic, por tokens, según su tarifa vigente.
- **Una suscripción Claude Pro o Max no incluye el uso de la API.** La API se contrata y factura aparte en la Consola de Claude.
- Precio de lista de Claude Opus 5.5 (octubre de 2026): **4 USD por millón de tokens de entrada** y **20 USD por millón de salida** (escritura en caché 5 USD, lectura 0,20 USD). El panel lo muestra y estima el coste de cada solicitud a partir de los tokens que informa la API.
- La cifra del panel es una **estimación**; la factura real (impuestos, descuentos o cambios de tarifa) está en https://platform.claude.com/settings/billing.

## Límites y control de solicitudes
- **Tu cuenta de Anthropic** tiene límites por minuto (solicitudes y tokens) según el nivel de tu organización. Si se alcanzan, el panel lo indica y puedes reintentar.
- **Video Studio AI** añade su propio control (Ajustes → Claude):
  - estimación previa de cuántas solicitudes necesita cada operación;
  - límite de solicitudes en 24 horas (30 por defecto) que exige tu confirmación para superarlo;
  - tope de solicitudes por operación, incluidos los reintentos;
  - tiempo máximo por solicitud y número de reintentos ante errores temporales;
  - historial de consumo de los últimos 30 días.
- Nada se envía a Claude sin una acción tuya («Generar plan», «Corregir», «Dirigir animaciones», «Modificar escena» o «Probar conexión»).

## Qué se envía
La transcripción con tiempos, los datos de escenas y rostros, tus preferencias y algunos fotogramas reducidos. **Nunca** el archivo de video. Anthropic conserva las entradas y salidas de la API durante un tiempo limitado según su política (https://privacy.claude.com).

## Errores que puedes ver
| Mensaje | Qué hacer |
|---|---|
| La clave de API no es válida o fue revocada | Crea otra en la Consola y guárdala. |
| Tu cuenta no tiene saldo o facturación activa | Añade crédito en la Consola (Billing). |
| Se alcanzó el límite de tu cuenta de la API | Espera y reintenta; revisa los límites de tu organización. |
| Tu cuenta no tiene acceso al modelo | Tu organización no tiene acceso a Claude Opus 5.5. |
| Sin conexión con la API | Revisa la conexión a internet o el proxy. |
| Claude está saturado | Temporal: el panel reintenta según tu configuración. |
| No hay un llavero del sistema disponible | Ver [TROUBLESHOOTING.md](TROUBLESHOOTING.md). |

## Por qué no se usa el inicio de sesión de Claude.ai (Pro/Max)
La documentación oficial de Anthropic indica que las aplicaciones de terceros no pueden ofrecer el inicio de sesión de Claude.ai ni enviar solicitudes a través de los planes Free, Pro o Max de sus usuarios (tampoco mediante el Claude Agent SDK ni el modo sin interfaz de Claude Code), salvo aprobación previa. Los desarrolladores deben usar claves de API de la Consola o de un proveedor de nube compatible.
- https://code.claude.com/docs/en/legal-and-compliance
- https://code.claude.com/docs/en/agent-sdk/overview

Por eso esta edición **solo** usa tu clave de API. El código del transporte por CLI existe únicamente para las pruebas automáticas, con un CLI simulado.

## Pruebas sin coste
Las pruebas automáticas usan una **API de Anthropic simulada** (`backend/tests/fake_anthropic.py`) y un CLI simulado: no hacen solicitudes reales ni generan cargos. Las pruebas con Claude real solo se ejecutan si se activan expresamente (`VSA_TEST_CLAUDE=1`) con una clave autorizada.

## Interfaz desacoplada
`backend/app/services/claude_client.py` expone una única función `run(prefs, system, blocks, schema)`. El mecanismo de autenticación es un detalle del transporte; se podrían añadir Amazon Bedrock, Google Vertex AI o Microsoft Foundry (con las credenciales del propio usuario) sin tocar el resto del editor.

## Marca
«Video Studio AI» es un producto independiente. Se puede decir que **usa Claude de Anthropic**, pero no se usan los logotipos de Anthropic ni el nombre «Claude Code» como parte del producto.
