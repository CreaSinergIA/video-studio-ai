#!/usr/bin/env bash
# Prepara un entorno aislado para las pruebas E2E y las ejecuta.
#  - VSA_E2E_HOME: directorio de datos temporal (base de datos nueva, sin tocar la real)
#  - VSA_E2E_STORAGE: carpeta de almacenamiento de prueba (por defecto, temporal;
#    se puede apuntar al disco externo para validar escritura real en él)
#  - VSA_E2E_MEDIA: videos de prueba generados con FFmpeg
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
BASE="${TMPDIR:-/tmp}/vsa-e2e"
# Solo se borra un directorio de datos marcado como entorno de pruebas (environment.json).
if [[ -e "$BASE/home/environment.json" ]] && ! grep -q '"kind": "test"' "$BASE/home/environment.json"; then
  echo "$BASE/home no está marcado como entorno de pruebas; no se borra."; exit 1
fi
rm -rf "$BASE/home"
mkdir -p "$BASE/home" "$BASE/media"
export VSA_E2E_HOME="$BASE/home"
export VSA_E2E_MEDIA="$BASE/media"
if [[ -z "${VSA_E2E_STORAGE:-}" ]]; then
  rm -rf "$BASE/disk"; mkdir -p "$BASE/disk"
  export VSA_E2E_STORAGE="$BASE/disk/VideoStudio"
else
  [[ -e "$VSA_E2E_STORAGE" ]] && { echo "VSA_E2E_STORAGE ya existe: $VSA_E2E_STORAGE (usa una ruta nueva)"; exit 1; }
fi
ff() { ffmpeg -hide_banner -loglevel error -y "$@"; }
M="$VSA_E2E_MEDIA"
[[ -f "$M/Entrevista horizontal.mp4" ]] || ff -f lavfi -i "testsrc2=size=1920x1080:rate=30:duration=12" -f lavfi -i "sine=frequency=440:duration=12,volume=0.6" -c:v libx264 -pix_fmt yuv420p -g 30 -c:a aac -shortest "$M/Entrevista horizontal.mp4"
[[ -f "$M/reel_vertical.mp4" ]] || ff -f lavfi -i "testsrc2=size=1080x1920:rate=30:duration=8" -f lavfi -i "sine=frequency=660:duration=8" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$M/reel_vertical.mp4"
[[ -f "$M/iPhone vertical.MOV" ]] || ff -display_rotation:v:0 90 -i "$M/Entrevista horizontal.mp4" -c copy "$M/iPhone vertical.MOV"
[[ -f "$M/hevc_60fps.mov" ]] || ff -f lavfi -i "testsrc=size=1080x1920:rate=60:duration=5" -f lavfi -i "anoisesrc=d=5:a=0.15" -c:v libx265 -pix_fmt yuv420p -tag:v hvc1 -x265-params log-level=none -c:a aac -shortest "$M/hevc_60fps.mov"
[[ -f "$M/master_prores.mov" ]] || ff -f lavfi -i "smptehdbars=size=1280x720:rate=25:duration=6" -f lavfi -i "sine=frequency=330:duration=6" -c:v prores_ks -profile:v 2 -c:a pcm_s16le -shortest "$M/master_prores.mov"
echo "falso" > "$M/no-es-video.mp4"
# Fase 2: voz sintetizada en español (frases con pausas) sobre un video vertical con un corte.
if command -v say >/dev/null && [[ ! -f "$M/voz_es.mp4" ]]; then
  V="Eddy (Español (España))"
  say -v "$V" -o "$M/f1.wav" --file-format=WAVE --data-format=LEI16@16000 "Hola a todos, bienvenidos a una nueva edición del programa."
  say -v "$V" -o "$M/f2.wav" --file-format=WAVE --data-format=LEI16@16000 "Hoy hablaremos de cómo la inteligencia artificial cambia la edición de vídeo."
  ff -i "$M/f1.wav" -f lavfi -i "anullsrc=r=16000:cl=mono" -i "$M/f2.wav" -filter_complex "[1]atrim=duration=1.5[s];[0][s][2]concat=n=3:v=0:a=1" "$M/voz.wav"
  ff -f lavfi -i "testsrc2=s=720x1280:r=30:d=6" -f lavfi -i "smptehdbars=s=720x1280:r=30:d=6" -i "$M/voz.wav" -filter_complex "[0][1]concat=n=2:v=1:a=0,format=yuv420p[v]" -map "[v]" -map 2:a -c:v libx264 -c:a aac -shortest "$M/voz_es.mp4"
  rm -f "$M/f1.wav" "$M/f2.wav" "$M/voz.wav"
fi
# Fase 3: CLI de Claude Code SIMULADO (sin red). Con VSA_E2E_CLAUDE=1 se usa el real.
BACKEND="$(cd ../backend && pwd)"
printf '#!/bin/sh\nexec "%s/.venv/bin/python" "%s/tests/fake_claude.py" "$@"\n' "$BACKEND" "$BACKEND" > "$BASE/fake-claude"
chmod +x "$BASE/fake-claude"
export VSA_E2E_FAKE_CLAUDE="$BASE/fake-claude"
(cd ../backend && uv sync --quiet)
# Fase 4: el navegador de render ya instalado por la app se enlaza (solo lectura) al entorno
# aislado; sin él, las pruebas de la Fase 4 se omiten.
ENGINES="${VSA_E2E_ENGINES:-$HOME/Library/Application Support/VideoStudioAI-Community/engines}"
[[ -d "$ENGINES" ]] && ln -sfn "$ENGINES" "$VSA_E2E_HOME/engines"
# Compilación propia de las pruebas: no reemplaza frontend/dist de la app en uso.
export VSA_E2E_DIST="$BASE/dist"
npx tsc -b && npx vite build --outDir "$VSA_E2E_DIST" --emptyOutDir --logLevel error
npx playwright test "$@"
