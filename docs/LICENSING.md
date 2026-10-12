# Licencias — propuesta y estado

> **Estado: PENDIENTE DE DECISIÓN DEL AUTOR.** Mientras no se añada un archivo `LICENSE`, el código original de este repositorio no concede derechos de uso a terceros (todos los derechos reservados). Este documento recoge la propuesta y los bloqueos detectados. No es asesoramiento legal.

## Qué cubriría la licencia del proyecto
**Solo el código original** de Video Studio AI:
- backend (`backend/app`);
- panel (`frontend/src`);
- componentes y estilos del motor (`renderer/src`);
- scripts y documentación propios.

**Nunca** cubriría:
- Remotion ni sus paquetes;
- el navegador de render;
- FFmpeg;
- los modelos (Whisper, YuNet);
- las fuentes;
- ninguna dependencia de npm o PyPI.

Todos ellos conservan sus licencias ([THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)).

## Propuesta
**Apache-2.0** para el código original, con un `NOTICE` que:
- remita a `THIRD_PARTY_NOTICES.md`;
- advierta que el editor depende de Remotion, que tiene licencia propia: las organizaciones de 4 o más personas necesitan su propia licencia de Remotion.

Motivos:
- Es una licencia permisiva conocida, con concesión explícita de patentes y protección de marca (§6). Esto conviene si el nombre «Video Studio AI» debe seguir siendo del autor.
- Permite reutilizar el núcleo en la edición privada sin obligación de publicar sus extensiones.
- `NOTICE` es el lugar natural para la atribución («Created by Gabo») sin imponer marcas en los videos de los usuarios.

**Alternativas:**
- **MIT:** más simple, sin cláusula de patentes ni de marca.
- **Una licencia *source-available* propia:** permitiría restringir usos comerciales, pero dejaría de ser open source y complicaría las contribuciones.

**No usar MIT ni Apache «para todo el conjunto»:** la distribución incluye componentes con licencias distintas, y no se puede relicenciar Remotion.

## Bloqueos y dudas antes de publicar
1. **Remotion (bloqueante hasta confirmar por escrito con Remotion):**
   - **Términos vigentes:** qué texto rige la 4.0.x. Hoy es el `LICENSE.md` breve; los *Terms* de la v5 se anuncian para Remotion 5.0.
   - **Código visible:** si publicar el código fuente completo (que el usuario puede ver y modificar) obliga a las empresas usuarias a tener su propia licencia, aunque sea evidente que la necesitan si superan el umbral.
   - **Facturación por render:** si cada render local de una empresa usuaria cuenta como uso de *Automators*.
   - **Obligaciones del autor:** que el autor, con licencia gratuita de persona, no asume ninguna al distribuir la aplicación.
2. **Claude:** la Community Edition usa solo claves de API de cada usuario (ver [CLAUDE.md](CLAUDE.md)). No se ofrece el inicio de sesión de Claude.ai, prohibido para terceros salvo aprobación.
3. **Modelos `mlx-community`:** sus fichas no declaran licencia. Se descargan, no se redistribuyen.
4. **Patentes de códecs (H.264/HEVC/AAC):** dependen del FFmpeg y de los codificadores del sistema del usuario. El proyecto no distribuye codificadores.
5. **Elección final de la licencia:** decisión del autor.
