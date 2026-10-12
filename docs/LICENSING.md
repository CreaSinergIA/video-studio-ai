# Licencias — estado

> Documento informativo; no es asesoramiento legal.

## Código original del proyecto
- **Pendiente:** la licencia sencilla del código original se elegirá al preparar la publicación en GitHub. Hasta entonces no hay archivo `LICENSE` (todos los derechos reservados).
- **Qué cubrirá:** solo el código original — backend (`backend/app`), panel (`frontend/src`), componentes y estilos del motor (`renderer/src`), lanzadores, scripts y documentación propios.
- **Nunca cubrirá** a terceros: Remotion y sus paquetes, el navegador de render, FFmpeg, Node.js, uv, los modelos (Whisper, YuNet), las fuentes ni ninguna dependencia de npm o PyPI. Todos conservan sus licencias ([THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)).
- **Importante para publicar:** sin una licencia, quien descargue el repositorio puede verlo pero no tiene concedido el derecho de usarlo o modificarlo. Elegir una licencia permisiva antes de publicar resuelve esto.

## Componentes de terceros: cómo se distribuyen
| Componente | Licencia | Cómo llega al usuario | Obligación para este proyecto |
|---|---|---|---|
| Remotion 4.0.x | Remotion License (propia, *source-available*) | dependencia independiente, instalada con `npm` desde su registro oficial; no está en el repositorio | Mantener el aviso: gratuito para personas, organizaciones sin ánimo de lucro y empresas de hasta 3 personas; las mayores necesitan su propia licencia (https://www.remotion.pro/license). Cada usuario es responsable de sus condiciones. |
| Chrome Headless Shell | términos de Google | descargado de Google en el equipo del usuario, con verificación | Ninguna redistribución. |
| FFmpeg 9.0.2 | GPL (compilaciones de Martin Riedl y Gyan Doshi) | descargado del proveedor en el equipo del usuario, solo si falta | Ninguna redistribución. Si algún día se **empaqueta** FFmpeg dentro de un instalador, habrá que cumplir la GPL (ofrecer el código fuente) o usar una compilación LGPL. |
| Node.js 24 LTS | MIT y componentes | descargado de nodejs.org solo si falta | Ninguna redistribución. |
| uv / Python 3.12 | MIT/Apache-2.0 · PSF | descargados solo si faltan | Ninguna redistribución. |
| Modelos Whisper (MLX y faster-whisper) | MIT (pesos de OpenAI; conversiones de faster-whisper MIT; las de `mlx-community` no declaran licencia) | descargados de Hugging Face a petición | Ninguna redistribución. |
| Bibliotecas CUDA (opcional) | licencia de NVIDIA | descargadas de PyPI por el usuario con `--cuda` | Ninguna redistribución. |
| YuNet (rostros) | MIT | **incluido** en el repositorio con su licencia | Mantener el aviso (hecho). |
| Fuentes | SIL OFL 1.1 | **incluidas** con su licencia | Mantener avisos; no venderlas por separado (hecho). |
| Dependencias npm/PyPI | MIT, ISC, BSD, Apache-2.0, MPL-2.0… | gestores de paquetes | Inventario en `docs/licenses/DEPENDENCIES.md`. |

## Impedimentos reales detectados
Ninguno impide distribuir el **código** gratuitamente:
1. **Licencia propia sin elegir** → elegir una licencia permisiva al publicar (decisión del autor).
2. **Remotion en organizaciones grandes** → no afecta a la distribución del código; el aviso ya está en el README, en el panel (Ajustes → Acerca de y → Animaciones) y en los avisos de terceros.
3. **FFmpeg GPL** → solo sería relevante si se empaquetara dentro de un instalador comercial; hoy cada usuario lo descarga de su proveedor.

No se ha contactado a ningún proveedor ni se usa ninguna licencia personal del autor.
