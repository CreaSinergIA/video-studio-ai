# Conexión con Claude

Video Studio AI usa **Claude Opus 5.5** de Anthropic como director creativo: analiza la transcripción y unos pocos fotogramas reducidos, y propone el plan de edición y la dirección de las animaciones.

## Mecanismo de esta edición: tu propia clave de API
- Cada usuario crea su clave en la **Consola de Anthropic** (https://console.anthropic.com) y la guarda en Ajustes → Claude.
- La clave se guarda en el **llavero del sistema**, en un servicio propio de esta edición (`VideoStudioAI-Community`). Nunca se guarda en el navegador, en la base de datos, en los registros ni en los archivos del proyecto.
- El uso se **factura en la cuenta de Anthropic del usuario**, según la tarifa y los límites de Anthropic. Video Studio AI es gratuito, pero **Claude no**: no hay acceso gratuito a Opus más allá de los créditos de prueba que Anthropic ofrezca.
- El editor incluye un control de solicitudes (estimación previa, límite en 24 h con confirmación y tope por operación) para que nada se gaste sin que lo sepas.
- **Qué se envía:** la transcripción con tiempos, los datos de escenas y rostros, tus preferencias y algunos fotogramas reducidos. **Nunca** el archivo de video. Anthropic conserva las entradas y salidas de la API un tiempo limitado según su política de datos (https://privacy.claude.com).

## Por qué no se usa el inicio de sesión de Claude.ai (Pro/Max)
La documentación oficial de Anthropic indica, entre otras cosas:
- Las aplicaciones de terceros no pueden ofrecer el inicio de sesión de Claude.ai ni enviar solicitudes a través de los planes Free, Pro o Max de sus usuarios, salvo aprobación previa.
- Esa restricción incluye los agentes creados con el Claude Agent SDK y el modo sin interfaz de Claude Code (`claude -p`).
- Los desarrolladores deben usar autenticación con clave de API, de la Consola o de un proveedor de nube compatible.

Fuentes:
- https://code.claude.com/docs/en/legal-and-compliance
- https://code.claude.com/docs/en/agent-sdk/overview

Por eso esta edición **no** incluye el transporte por Claude Code ni el inicio de sesión de Claude.ai. El código del transporte por CLI solo se activa en el entorno de pruebas automáticas, con un CLI simulado.

## Interfaz desacoplada
`backend/app/services/claude_client.py` expone una única función `run(prefs, system, blocks, schema)`. El mecanismo de autenticación es un detalle del transporte, lo que permitirá añadir otros mecanismos autorizados sin tocar el resto del editor:
- **Hoy:** Messages API con clave del usuario.
- **Previstos:** Amazon Bedrock, Google Vertex AI o Microsoft Foundry, con las credenciales del propio usuario.

## Marca
«Video Studio AI» es un producto independiente. Se puede decir que **usa Claude de Anthropic**, pero no se usan los logotipos de Anthropic ni el nombre «Claude Code» como parte del producto.

## Pendiente
- **Almacenamiento de la clave en Windows:** el llavero actual usa la herramienta `security` de macOS. Windows necesita el Administrador de credenciales (siguiente fase).
- **Bedrock, Vertex o Foundry:** opcionales, siguiente fase.
