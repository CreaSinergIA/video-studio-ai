# Licencias

> Documento informativo; no es asesoramiento legal.

## Código original: MIT
- El código y la documentación originales de Video Studio AI — Community Edition se publican bajo la licencia **MIT** ([LICENSE](../LICENSE)), © 2026 Gabo.
- **Cubre:** backend (`backend/app`, `backend/tests`, `backend/migrations`), panel (`frontend/src`, `frontend/e2e`), componentes y estilos del motor (`renderer/src`, `renderer/scripts`), lanzadores, scripts, capturas de pantalla y documentación propios.
- **No cubre ni sustituye** las licencias de terceros: Remotion y sus paquetes, el navegador de render, FFmpeg, Node.js, uv, Python, los modelos (Whisper, faster-whisper, YuNet), las fuentes ni ninguna dependencia de npm o PyPI. Todos conservan sus licencias ([THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)).

## Componentes de terceros: cómo se distribuyen
| Componente | Licencia | Cómo llega al usuario | Obligación para este proyecto |
|---|---|---|---|
| Remotion 4.0.x | Remotion License (propia, *source-available*) | dependencia independiente, instalada con `npm` desde su registro oficial; no está en el repositorio | Mantener el aviso: gratuito para personas, organizaciones sin ánimo de lucro y empresas de hasta 3 personas; las mayores necesitan su propia licencia (https://www.remotion.pro/license). Cada usuario es responsable de sus condiciones. |
| Chrome Headless Shell | términos de Google | descargado de Google en el equipo del usuario, con verificación | Ninguna redistribución. |
| FFmpeg 9.0.2 | GPL (compilaciones de Martin Riedl y Gyan Doshi) | descargado del proveedor en el equipo del usuario, solo si falta | Ninguna redistribución. Si algún día se **empaqueta** FFmpeg dentro de un instalador, habrá que cumplir la GPL o usar una compilación LGPL. |
| Node.js 24 LTS | MIT y componentes | descargado de nodejs.org solo si falta | Ninguna redistribución. |
| uv / Python 3.12 | MIT/Apache-2.0 · PSF | descargados solo si faltan | Ninguna redistribución. |
| Modelos Whisper (MLX y faster-whisper) | MIT (pesos de OpenAI; conversiones de faster-whisper MIT; las de `mlx-community` no declaran licencia) | descargados de Hugging Face a petición | Ninguna redistribución. |
| Bibliotecas CUDA (opcional) | licencia de NVIDIA | descargadas de PyPI por el usuario con `--cuda` | Ninguna redistribución. |
| YuNet (rostros) | MIT | **incluido** en el repositorio con su licencia | Mantener el aviso (hecho). |
| Fuentes | SIL OFL 1.1 | **incluidas** con su licencia | Mantener avisos; no venderlas por separado (hecho). |
| Dependencias npm/PyPI | MIT, ISC, BSD, Apache-2.0, MPL-2.0… | gestores de paquetes | Inventario en `docs/licenses/DEPENDENCIES.md`. |

## Revisión de publicación
- No se publica ningún binario descargable de terceros (modelos, navegadores, FFmpeg, Node.js, `node_modules`, entornos de Python): el instalador los descarga de sus fuentes.
- No se detectó ningún archivo cuya publicación no esté autorizada. Los únicos recursos de terceros incluidos (fuentes OFL y YuNet MIT) permiten la redistribución con su aviso.
- No se ha contactado a ningún proveedor ni se usa ninguna licencia personal del autor.
