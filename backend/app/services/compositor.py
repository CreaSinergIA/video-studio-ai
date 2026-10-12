"""Composición final con animaciones (Fase 4): FFmpeg sobre el pipeline de exportación.

Capas (de abajo arriba):
1. Video original (escalado al tamaño de salida; movimientos de cámara aprobados; desenfoque
   cuando el plan pide fondo desenfocado).
2. Animaciones: clips ProRes 4444 con transparencia renderizados por Remotion, colocados en su
   tiempo exacto (inicio aprobado) y activos solo en su intervalo.
3. Picture-in-picture: el original encima de una animación a pantalla completa cuando el plan
   lo pide (mismo instante, recorte centrado en el rostro).
4. Subtítulos de la Fase 2 con el tratamiento aprobado por tramo (mantener/ocultar/mover).

Audio: la voz original intacta (`normalize=0`), efectos sincronizados atenuados bajo la voz
(`sidechaincompress`) y limitador final. Sin efectos, el audio se copia como en la Fase 2.

El mismo código produce las vistas previas por tramo (ventana [t0, t1], resolución reducida).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services import sfx as sfx_lib
from app.services.exporter import ExportPlan
from app.services.media_tools import run_ffmpeg

# Volumen de los efectos respecto a la voz con sfx_volume=100 (−12 dB): la voz manda.
# Mezcla de efectos (Fase 4.1). Los efectos se sitúan RESPECTO A LA VOZ medida del video:
# su energía en el instante (RMS de 100 ms de la muestra) queda a «offset» dB de la sonoridad
# integrada de la voz. v1 usaba una ganancia fija (−12 dB) sobre muestras normalizadas por pico
# y un ducking que restaba ~14 dB bajo la voz: los efectos quedaban 28–40 dB por debajo.
SFX_INTENSITY_DB = {"soft": -13.0, "balanced": -8.0, "strong": -4.0}
VOICE_REFERENCE_LUFS = -16.0  # si el original no tiene voz
# Ducking moderado: solo cuando la voz es fuerte y como mucho unos 3–4 dB.
DUCKING = "threshold=0.1:ratio=1.8:attack=15:release=220:knee=4"
LIMITER = "alimiter=limit=1:attack=1:release=20:level=false:latency=1"
# Fase 5: techo de pico verdadero para distribución digital. La mezcla se ajusta con una
# ganancia fija (no altera la dinámica de la voz) para dejar el pico de la voz en el techo, y un
# limitador sobremuestreado ×4 (aproxima el pico entre muestras) recoge lo que sumen los efectos.
TRUE_PEAK_CEILING_DBTP = -1.0


def true_peak_chain(sample_rate: int) -> str:
    limit = 10 ** ((TRUE_PEAK_CEILING_DBTP - 0.3) / 20)
    return (
        f"aresample={sample_rate * 4},"
        f"alimiter=limit={limit:.4f}:attack=1:release=20:level=false:latency=1,"
        f"aresample={sample_rate}"
    )


def ceiling_trim_db(voice_tp: float | None) -> float:
    """Ganancia fija (≤ 0) que deja el pico verdadero de la voz 0,4 dB bajo el techo: por debajo
    del umbral del limitador (techo − 0,3 dB), que así nunca actúa sobre la voz."""
    if voice_tp is None:
        return 0.0
    return round(min(0.0, TRUE_PEAK_CEILING_DBTP - 0.4 - voice_tp), 2)


def sfx_gain_db(kind: str, comp: Composition, cue_gain: float = 0.0) -> float:
    """Ganancia de un efecto: nivel objetivo respecto a la voz − nivel de referencia de la
    muestra + equilibrio por tipo + ajuste de volumen del usuario + intensidad de la escena."""
    voice = comp.voice_lufs if comp.voice_lufs is not None else VOICE_REFERENCE_LUFS
    target = voice + SFX_INTENSITY_DB.get(comp.sfx_intensity, SFX_INTENSITY_DB["balanced"])
    trim = max(-24.0, 20 * math.log10(max(1, comp.sfx_volume) / 70))  # 70 % = 0 dB
    return target - sfx_lib.TARGET_RMS_DBFS + sfx_lib.BALANCE_DB.get(kind, 0.0) + trim + cue_gain


@dataclass
class ClipLayer:
    path: Path
    start: float
    end: float
    mode: str  # overlay | fullscreen | transition
    pip_src: dict[str, float] | None = None  # recorte del original (normalizado)
    pip_box: dict[str, Any] | None = None  # destino en el encuadre (normalizado) + forma
    blur: bool = False
    # Fase 5: el clip cubre solo esta zona del encuadre de su especificación (píxeles); None =
    # encuadre completo. ``frame_size`` es el tamaño de ese encuadre.
    viewport: dict[str, int] | None = None
    frame_size: tuple[int, int] | None = None


@dataclass
class CameraMove:
    start: float
    end: float
    kind: str  # slow_push_in | punch_in | pull_out | reframe | pan
    cx: float = 0.5
    cy: float = 0.4


@dataclass
class SfxCue:
    kind: str
    at: float
    gain_db: float = 0.0
    variant: int = 0


@dataclass
class Composition:
    clips: list[ClipLayer] = field(default_factory=list)
    camera: list[CameraMove] = field(default_factory=list)
    sfx: list[SfxCue] = field(default_factory=list)
    sfx_volume: int = 70  # 0–100 (preferencias del preset)
    duration: float = 0.0  # duración del original (para el audio de originales sin voz)
    sample_rate: int = 48000  # frecuencia del audio original (se conserva)
    sfx_intensity: str = "balanced"  # soft | balanced | strong (preferencias del proyecto)
    voice_lufs: float | None = None  # sonoridad integrada medida de la voz original
    voice_tp: float | None = None  # pico verdadero medido de la voz original (dBTP)
    channel_layout: str = "stereo"  # disposición de canales de la voz original (se conserva)
    fps_rate: str = "30"  # FPS del original como fracción (para la cámara con zoompan)


def _between(intervals: list[tuple[float, float]]) -> str:
    return "+".join(f"between(t,{a:.4f},{b:.4f})" for a, b in intervals) or "0"


def _zoom_expr(moves: list[CameraMove]) -> tuple[str, str, str]:
    """Expresiones Z(t), cx(t), cy(t) por tramos (fuera de los tramos Z=1); `t` es el tiempo
    del fotograma de entrada (`in_time` en zoompan)."""
    z = "1"
    cx = "0.5"
    cy = "0.5"
    for m in moves:
        d = max(0.05, m.end - m.start)
        prog = f"min(max((in_time-{m.start:.4f})/{d:.4f},0),1)"
        if m.kind == "punch_in":
            val = f"(1+0.12*min(max((in_time-{m.start:.4f})/0.18,0),1))"
        elif m.kind == "pull_out":
            val = f"(1.1-0.1*{prog})"
        elif m.kind in ("reframe", "pan"):
            val = "1.06"
        else:  # slow_push_in
            val = f"(1+0.07*{prog})"
        cond = f"between(in_time,{m.start:.4f},{m.end:.4f})"
        z = f"if({cond},{val},{z})"
        cx = f"if({cond},{m.cx:.4f},{cx})"
        cy = f"if({cond},{m.cy:.4f},{cy})"
    return z, cx, cy


def build_args(
    src: Path,
    out: Path,
    plan: ExportPlan,
    comp: Composition,
    subtitles: Path | None,
    *,
    window: tuple[float, float] | None = None,
    preview: bool = False,
    audio_tracks: int = 1,
) -> list[str]:
    """Argumentos de FFmpeg para la composición (exportación completa o ventana de vista previa)."""
    t0 = window[0] if window else 0.0
    W, H = plan.width, plan.height
    args: list[str] = []
    seek = ["-ss", f"{t0:.4f}", "-t", f"{window[1] - window[0]:.4f}"] if window else []
    args += [*seek, "-i", str(src)]
    n_in = 1
    sub_idx = None
    if subtitles is not None:
        args += [*seek, "-f", "concat", "-safe", "0", "-i", str(subtitles)]
        sub_idx = n_in
        n_in += 1
    clip_idx: list[int] = []
    for c in comp.clips:
        args += ["-itsoffset", f"{max(0.0, c.start - t0):.4f}", "-i", str(c.path)]
        clip_idx.append(n_in)
        n_in += 1
    sfx_idx: list[tuple[int, SfxCue]] = []
    cues = [s for s in comp.sfx if (not window or window[0] - 0.05 <= s.at <= window[1])]
    if comp.sfx_volume > 0:
        for s in cues:
            args += ["-i", str(sfx_lib.path_for(s.kind, s.variant))]
            sfx_idx.append((n_in, s))
            n_in += 1

    fc: list[str] = []
    base = []
    if plan.fps != "original":
        base.append(f"fps={plan.fps}")
    base.append(f"scale={W}:{H}:flags=lanczos")
    # Profundidad del destino: un original de 10 bits no se reduce a 8 al componer.
    deep = not preview and "10" in plan.pix_fmt
    fmt, afmt, amax = (
        ("yuv444p10le", "yuva444p10le", 1023) if deep else ("yuv444p", "yuva444p", 255)
    )
    fc.append(f"[0:v]{','.join(base)},format={fmt},setsar=1[v0]")
    cur = "v0"
    if comp.camera:
        z, cx, cy = _zoom_expr(
            [CameraMove(m.start - t0, m.end - t0, m.kind, m.cx, m.cy) for m in comp.camera]
        )
        # zoompan recorta (iw/zoom × ih/zoom) en x, y por fotograma y escala al tamaño fijo:
        # el encuadre se acerca al centro indicado (rostro) sin cambiar tamaño ni FPS.
        rate = plan.fps if plan.fps != "original" else comp.fps_rate
        fc.append(
            f"[{cur}]zoompan=z='{z}':x='(iw-iw/zoom)*({cx})':y='(ih-ih/zoom)*({cy})':d=1:s={W}x{H}:fps={rate},format={fmt},setsar=1[vcam]"
        )
        cur = "vcam"
    blur_iv = [(c.start - t0, c.end - t0) for c in comp.clips if c.blur]
    if blur_iv:
        fc.append(
            f"[{cur}]split[vb0][vb1];[vb1]boxblur=luma_radius=24:luma_power=2[vbl];[vb0][vbl]overlay=enable='{_between(blur_iv)}'[vblur]"
        )
        cur = "vblur"
    pip_layers = [(i, c) for i, c in enumerate(comp.clips) if c.pip_src and c.pip_box]
    if pip_layers:
        fc.append(
            f"[{cur}]split={len(pip_layers) + 1}[vmain]"
            + "".join(f"[vpip{i}]" for i, _ in pip_layers)
        )
        cur = "vmain"
    for k, (c, idx) in enumerate(zip(comp.clips, clip_idx, strict=True)):
        a, b = c.start - t0, c.end - t0
        ox, oy, vw, vh = 0, 0, W, H
        if c.viewport and c.frame_size:
            rx, ry = W / c.frame_size[0], H / c.frame_size[1]
            ox, oy = round(c.viewport["x"] * rx), round(c.viewport["y"] * ry)
            vw, vh = max(2, round(c.viewport["w"] * rx)), max(2, round(c.viewport["h"] * ry))
        fc.append(f"[{idx}:v]scale={vw}:{vh}:flags=bicubic,format={afmt},setsar=1[a{k}]")
        fc.append(
            f"[{cur}][a{k}]overlay={ox}:{oy}:eof_action=pass:enable='between(t,{a:.4f},{b:.4f})'[o{k}]"
        )
        cur = f"o{k}"
        if c.pip_src and c.pip_box:
            sb, d = c.pip_src, c.pip_box
            pw, ph = max(2, int(d["w"] * W) // 2 * 2), max(2, int(d["h"] * H) // 2 * 2)
            px, py = int(d["x"] * W), int(d["y"] * H)
            cw, ch = f"iw*{sb['w']:.4f}", f"ih*{sb['h']:.4f}"
            crop = f"crop=w='min({cw},iw)':h='min({ch},ih)':x='max(0,min(iw*{sb['x']:.4f},iw-{cw}))':y='max(0,min(ih*{sb['y']:.4f},ih-{ch}))'"
            fin = f"fade=t=in:st={a + 0.08:.4f}:d=0.25:alpha=1,fade=t=out:st={max(a, b - 0.35):.4f}:d=0.3:alpha=1"
            if d.get("shape") == "circle":
                r = min(pw, ph) // 2
                mask = f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='if(lte(hypot(X-{pw / 2},Y-{ph / 2}),{r}),{amax},0)'"
            else:
                rr = int(min(pw, ph) * 0.08)
                mask = (
                    f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='if(lte(hypot(max({rr}-X,max(0,X-{pw - rr})),"
                    f"max({rr}-Y,max(0,Y-{ph - rr}))),{rr}),{amax},0)'"
                )
            fc.append(
                # Solo el tramo del PiP (la máscara por píxel no se calcula en todo el video);
                # trim conserva las marcas de tiempo, así que fundidos y enable no cambian.
                f"[vpip{k}]trim=start={max(0.0, a - 0.05):.4f}:end={b + 0.05:.4f},{crop},scale={pw}:{ph}:force_original_aspect_ratio=increase,crop={pw}:{ph},format={afmt},{mask},{fin}[p{k}]"
            )
            fc.append(
                f"[{cur}][p{k}]overlay={px}:{py}:eof_action=pass:enable='between(t,{a:.4f},{b:.4f})'[q{k}]"
            )
            cur = f"q{k}"
    if sub_idx is not None:
        fc.append(f"[{sub_idx}:v]format=rgba[sub]")
        fc.append(f"[{cur}][sub]overlay=0:0:eof_action=pass:format=auto[vs]")
        cur = "vs"
    fc.append(f"[{cur}]format={plan.pix_fmt if not preview else 'yuv420p'}[vout]")

    # Audio
    amap: list[str]
    if sfx_idx:
        parts = []
        for j, (idx, s) in enumerate(sfx_idx):
            delay = max(0, round((s.at - t0) * 1000))
            parts.append(
                f"[{idx}:a]aformat=sample_rates={comp.sample_rate}:channel_layouts={comp.channel_layout},adelay={delay}:all=1,volume={sfx_gain_db(s.kind, comp, s.gain_db):.2f}dB[s{j}]"
            )
        fc += parts
        mix_in = "".join(f"[s{j}]" for j in range(len(sfx_idx)))
        fc.append(f"{mix_in}amix=inputs={len(sfx_idx)}:normalize=0:duration=longest[sfxbus]")
        if audio_tracks > 0:
            # La voz conserva su frecuencia y su disposición de canales; los efectos se adaptan.
            fc.append("[0:a:0]asplit=2[voice][key]")
            fc.append(f"[sfxbus][key]sidechaincompress={DUCKING}[sfxduck]")
            trim = ceiling_trim_db(comp.voice_tp)
            fc.append(
                f"[voice][sfxduck]amix=inputs=2:normalize=0:duration=first,volume={trim:.2f}dB,"
                f"{true_peak_chain(comp.sample_rate)}[aout]"
            )
        else:
            # Original sin audio: solo los efectos, con la duración del video.
            dur = (window[1] - window[0]) if window else comp.duration
            fc.append(
                f"[sfxbus]apad=whole_dur={dur:.4f},atrim=0:{dur:.4f},"
                f"{true_peak_chain(comp.sample_rate)}[aout]"
            )
        codec = (
            ["-c:a", "pcm_s24le"]
            if plan.container == "mov" and not preview
            else ["-c:a", "aac", "-b:a", "320k" if not preview else "160k"]
        )
        amap = ["-map", "[aout]", *codec]
        # Pistas de audio adicionales del original: se conservan tal cual.
        for k in range(1, audio_tracks):
            amap += ["-map", f"0:a:{k}?", f"-c:a:{k}", "copy"]
    else:
        amap = (
            list(plan.audio_args)
            if not preview
            else ["-map", "0:a?", "-c:a", "aac", "-b:a", "160k"]
        )

    args += ["-filter_complex", ";".join(fc), "-map", "[vout]", *amap]
    if preview:
        venc = "h264_videotoolbox" if "h264_videotoolbox" in plan.video_args else None
        if venc:
            args += ["-c:v", venc, "-q:v", "62"]
        else:
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
        args += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    else:
        args += [
            *plan.video_args,
            "-pix_fmt",
            plan.pix_fmt,
            *plan.color_args,
            "-map_metadata",
            "0",
            "-movflags",
            "+faststart",
        ]
    if plan.fps == "original":
        args += ["-fps_mode", "passthrough"]
    args.append(str(out))
    return args


def compose(
    src: Path,
    out: Path,
    plan: ExportPlan,
    comp: Composition,
    subtitles: Path | None,
    duration: float,
    *,
    window: tuple[float, float] | None = None,
    preview: bool = False,
    audio_tracks: int = 1,
    on_progress: Any = None,
    cancel: Any = None,
) -> None:
    args = build_args(
        src, out, plan, comp, subtitles, window=window, preview=preview, audio_tracks=audio_tracks
    )
    span = (window[1] - window[0]) if window else duration
    run_ffmpeg(get_settings().ffmpeg, args, duration=span, on_progress=on_progress, cancel=cancel)


def preview_plan(width: int, height: int, short_side: int = 540) -> ExportPlan:
    """Plan reducido para vistas previas (mismo encuadre, menor resolución, 30 fps)."""
    k = short_side / min(width, height)
    w = max(2, round(width * k / 2) * 2)
    h = max(2, round(height * k / 2) * 2)
    return ExportPlan(
        width=w,
        height=h,
        fps="30",
        container="mp4",
        video_codec="h264",
        encoder="h264_videotoolbox",
        video_args=["-c:v", "h264_videotoolbox"],
        pix_fmt="yuv420p",
        audio_args=["-map", "0:a?", "-c:a", "aac", "-b:a", "160k"],
        color_args=[],
        estimated_bytes=0,
    )
