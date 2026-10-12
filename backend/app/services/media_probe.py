"""Inspección de archivos multimedia con ffprobe y validación del formato real."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from app import limits

ALLOWED_EXTENSIONS = {".mp4": "mp4", ".mov": "mov"}
ISO_BMFF_BOXES = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot", b"uuid"}

# Códecs que Safari y Chrome (macOS) reproducen de forma nativa.
WEB_VIDEO_CODECS = {
    "h264": {"yuv420p", "yuvj420p"},
    "hevc": {"yuv420p", "yuvj420p", "yuv420p10le"},
    "av1": {"yuv420p", "yuv420p10le"},
    "vp9": {"yuv420p"},
}
WEB_AUDIO_CODECS = {"aac", "mp3", "opus", "flac", "alac"}
HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}
# ffprobe solo abre archivos locales con el demuxer MP4/MOV: un archivo hostil con otra
# extensión real (listas HLS, concat…) no llega a abrir red ni otros archivos.
SAFE_INPUT_ARGS = ["-protocol_whitelist", "file", "-format_whitelist", "mov,mp4,m4a,3gp,3g2,mj2"]


class MediaValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def looks_like_iso_bmff(head: bytes) -> bool:
    """Comprueba la firma de contenedor ISO-BMFF/QuickTime (MP4/MOV) en los primeros bytes."""
    return len(head) >= 8 and head[4:8] in ISO_BMFF_BOXES


def extension_container(filename: str) -> str | None:
    return ALLOWED_EXTENSIONS.get(Path(filename).suffix.lower())


@dataclass
class AudioTrack:
    index: int
    codec: str
    channels: int | None
    channel_layout: str | None
    sample_rate: int | None
    bit_rate: int | None
    language: str | None
    title: str | None


@dataclass
class MediaInfo:
    container: str
    format_name: str
    major_brand: str | None
    duration: float
    size_bytes: int
    bit_rate: int | None
    width: int
    height: int
    display_width: int
    display_height: int
    rotation: int
    orientation: str
    fps: float
    fps_num: int
    fps_den: int
    video_codec: str
    video_profile: str | None
    pix_fmt: str | None
    bit_depth: int | None
    color_transfer: str | None
    frame_count: int | None
    creation_time: str | None
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def asset_fields(self) -> dict[str, Any]:
        """Campos técnicos de `MediaAsset` medidos en el propio archivo."""
        return {
            "container": self.container,
            "format_name": self.format_name,
            "major_brand": self.major_brand,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "display_width": self.display_width,
            "display_height": self.display_height,
            "rotation": self.rotation,
            "orientation": self.orientation,
            "fps": self.fps,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "video_codec": self.video_codec,
            "video_profile": self.video_profile,
            "pix_fmt": self.pix_fmt,
            "bit_depth": self.bit_depth,
            "color_transfer": self.color_transfer,
            "bit_rate": self.bit_rate,
            "frame_count": self.frame_count,
            "has_audio": self.has_audio,
            "audio_tracks": [t.__dict__ for t in self.audio_tracks],
            "creation_time": self.creation_time,
            "probe": self.raw,
            "browser_playable": self.browser_playable,
        }

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_tracks)

    @property
    def is_hdr(self) -> bool:
        return self.color_transfer in HDR_TRANSFERS

    @property
    def browser_playable(self) -> bool:
        allowed_pix = WEB_VIDEO_CODECS.get(self.video_codec)
        if allowed_pix is None or (self.pix_fmt and self.pix_fmt not in allowed_pix):
            return False
        return all(track.codec in WEB_AUDIO_CODECS for track in self.audio_tracks[:1])


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None  # descarta NaN


def _rate(value: str | None) -> Fraction | None:
    if not value or value in ("0/0", "0/1"):
        return None
    try:
        frac = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return frac if 0 < frac < 1000 else None


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return (_int(side["rotation"]) or 0) % 360
    rot = _int((stream.get("tags") or {}).get("rotate"))
    return (rot or 0) % 360


def run_ffprobe(ffprobe: str, path: Path, timeout: float = 60) -> dict[str, Any]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        *SAFE_INPUT_ARGS,
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise MediaValidationError(
            "ffprobe_missing",
            "No se encontró ffprobe. Ejecuta el instalador de Video Studio AI de nuevo.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaValidationError(
            "probe_timeout", "ffprobe tardó demasiado en analizar el archivo."
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise MediaValidationError(
            "unreadable_media",
            "El archivo no es un video legible" + (f": {detail[-1]}" if detail else "."),
        )
    try:
        return json.loads(proc.stdout or b"{}")
    except json.JSONDecodeError as exc:
        raise MediaValidationError("unreadable_media", "Respuesta de ffprobe no válida.") from exc


def parse_probe(data: dict[str, Any], filename: str) -> MediaInfo:
    fmt = data.get("format") or {}
    format_name = str(fmt.get("format_name") or "")
    if not any(token in format_name.split(",") for token in ("mov", "mp4")):
        raise MediaValidationError(
            "unsupported_format",
            f"Formato no compatible ({format_name or 'desconocido'}). Solo se admiten MP4 y MOV.",
        )
    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    major_brand = (tags.get("major_brand") or "").strip() or None
    ext_container = extension_container(filename)
    if ext_container is None:
        raise MediaValidationError(
            "unsupported_extension", "Extensión no admitida. Usa archivos .mp4 o .mov."
        )
    container = "mov" if major_brand == "qt" else ("mp4" if major_brand else ext_container)

    streams = data.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise MediaValidationError("no_video_stream", "El archivo no contiene una pista de video.")
    width = _int(video.get("width")) or 0
    height = _int(video.get("height")) or 0
    if width <= 0 or height <= 0:
        raise MediaValidationError("invalid_dimensions", "No se pudo leer la resolución del video.")
    if max(width, height) > limits.MAX_LONG_SIDE or width * height > limits.MAX_PIXELS:
        raise MediaValidationError(
            "too_large",
            f"La resolución {width}×{height} supera el máximo admitido (8K). Reduce el video "
            "antes de importarlo.",
        )

    duration = _float(fmt.get("duration")) or _float(video.get("duration")) or 0.0
    if duration <= 0:
        raise MediaValidationError("invalid_duration", "No se pudo leer la duración del video.")
    if duration > limits.MAX_DURATION_SECONDS:
        raise MediaValidationError(
            "too_long",
            f"El video dura {duration / 3600:.1f} h; el máximo admitido es "
            f"{limits.MAX_DURATION_SECONDS / 3600:.0f} h. Divídelo en partes.",
        )

    rotation = _rotation(video)
    display_w, display_h = (height, width) if rotation in (90, 270) else (width, height)
    if display_h > display_w:
        orientation = "vertical"
    elif display_h == display_w:
        orientation = "square"
    else:
        orientation = "horizontal"

    rate = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate")) or Fraction(30)
    rate = rate.limit_denominator(1001)
    if float(rate) > limits.MAX_FPS:
        raise MediaValidationError(
            "too_many_fps", f"{float(rate):.0f} fotogramas por segundo superan el máximo admitido."
        )

    bit_depth = _int(video.get("bits_per_raw_sample"))
    pix_fmt = video.get("pix_fmt")
    if bit_depth is None and isinstance(pix_fmt, str):
        bit_depth = 10 if "10" in pix_fmt else 12 if "12" in pix_fmt else 8

    audio_tracks = [
        AudioTrack(
            index=_int(s.get("index")) or 0,
            codec=str(s.get("codec_name") or "desconocido"),
            channels=_int(s.get("channels")),
            channel_layout=s.get("channel_layout"),
            sample_rate=_int(s.get("sample_rate")),
            bit_rate=_int(s.get("bit_rate")),
            language=(s.get("tags") or {}).get("language"),
            title=(s.get("tags") or {}).get("handler_name") or (s.get("tags") or {}).get("title"),
        )
        for s in streams
        if s.get("codec_type") == "audio"
    ]

    return MediaInfo(
        container=container,
        format_name=format_name,
        major_brand=major_brand,
        duration=round(duration, 3),
        size_bytes=_int(fmt.get("size")) or 0,
        bit_rate=_int(fmt.get("bit_rate")),
        width=width,
        height=height,
        display_width=display_w,
        display_height=display_h,
        rotation=rotation,
        orientation=orientation,
        fps=round(float(rate), 3),
        fps_num=rate.numerator,
        fps_den=rate.denominator,
        video_codec=str(video.get("codec_name") or "desconocido"),
        video_profile=video.get("profile"),
        pix_fmt=pix_fmt,
        bit_depth=bit_depth,
        color_transfer=video.get("color_transfer"),
        frame_count=_int(video.get("nb_frames")),
        creation_time=tags.get("creation_time"),
        audio_tracks=audio_tracks,
        raw=data,
    )


def probe_file(ffprobe: str, path: Path, filename: str | None = None) -> MediaInfo:
    return parse_probe(run_ffprobe(ffprobe, path), filename or path.name)
