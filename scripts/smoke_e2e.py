"""Prueba de humo de punta a punta, igual en macOS y en Windows.

Recorre por la API local, contra una instalación **aislada** (carpeta de datos y almacenamiento
temporales, otro puerto), todo el flujo de la Community Edition:

 1. Arranque con el lanzador, token de sesión obligatorio.
 2. Primera configuración: comprobaciones del equipo, carpeta de proyectos.
 3. Modelo de transcripción y navegador de render (los descarga si faltan).
 4. Conexión con Claude con una clave de prueba contra una API de Anthropic **simulada**
    (sin red ni cargos): verificación gratuita y solicitud de prueba.
 5. Para cada estilo (Motion Tech, Minimal Motion, Creative Explainer): importar un video
    sintético con voz, transcribir de verdad, plan, aprobación, animaciones (Remotion real),
    vista previa, efectos de sonido y exportación verificada; sin marcas de agua.
 6. Regeneración de una escena (versión candidata, vista previa y aplicación).
 7. Reinicio del panel: los proyectos y exportaciones persisten.
 8. Cierre: ningún proceso del servidor queda vivo.

Uso (desde la raíz del repositorio, después del instalador):
    macOS:   backend/.venv/bin/python scripts/smoke_e2e.py
    Windows: backend\\.venv\\Scripts\\python.exe scripts\\smoke_e2e.py

Opciones: --report <json>, --keep (no borra la carpeta temporal), --model <id>,
--models-dir <carpeta con modelos ya descargados>, --engines-dir <navegador ya descargado>,
--styles motion_tech,minimal_motion,creative_explainer.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

STYLES = ["motion_tech", "minimal_motion", "creative_explainer"]
TEXT_ES = (
    "Hola a todos, bienvenidos a una nueva edición del programa. Hoy hablaremos de cómo la "
    "inteligencia artificial cambia la edición de vídeo."
)


class SmokeError(Exception):
    pass


class Smoke:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base = Path(tempfile.mkdtemp(prefix="vsa-smoke-"))
        self.home = self.base / "home"
        self.storage = self.base / "disk" / "VideoStudio"
        (self.base / "disk").mkdir(parents=True)
        self.media = self.base / "media"
        self.media.mkdir()
        self.port = self._free_port()
        self.results: list[dict[str, Any]] = []
        self.token = ""
        self.fake_api: Any = None
        self.env = {
            **os.environ,
            "VSA_HOME": str(self.home),
            "VSA_PORT": str(self.port),
            "VSA_NO_BROWSER": "1",
            "VSA_ENV": "test",  # entorno de pruebas marcado: nunca abre datos del usuario
            "PYTHONUTF8": "1",
        }
        self.env.pop("VSA_SESSION_TOKEN", None)
        if args.models_dir:
            self.env["VSA_MODELS_DIR"] = str(Path(args.models_dir).resolve())

    # -- utilidades --------------------------------------------------------

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def step(self, name: str, fn: Any) -> Any:
        started = time.monotonic()
        print(f"\n▶ {name}", flush=True)
        try:
            detail = fn()
        except Exception as exc:
            self.results.append(
                {"step": name, "ok": False, "seconds": round(time.monotonic() - started, 1),
                 "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
            )  # fmt: skip
            print(f"  ✗ {type(exc).__name__}: {exc}", flush=True)
            raise
        self.results.append(
            {"step": name, "ok": True, "seconds": round(time.monotonic() - started, 1),
             "detail": detail}
        )  # fmt: skip
        print(f"  ✓ {detail if isinstance(detail, str) else 'ok'}", flush=True)
        return detail

    def http(
        self, method: str, path: str, body: Any = None, *, raw: bytes | None = None,
        token: bool = True, expect: int | tuple[int, ...] = (200, 201, 202, 204), timeout: float = 120,
    ) -> Any:  # fmt: skip
        headers = {"x-vsa-client": "1"}
        if token:
            headers["x-vsa-token"] = self.token
        data = None
        if raw is not None:
            data = raw
            headers["content-type"] = "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers=headers
        )
        expected = (expect,) if isinstance(expect, int) else expect
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, payload = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, payload = err.code, err.read()
        if status not in expected:
            raise SmokeError(f"{method} {path} → {status}: {payload[:400]!r}")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except ValueError:
            return payload

    def wait_jobs(self, timeout: float = 1800) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            jobs = self.http("GET", "/api/jobs?recent_seconds=0")
            if not any(j["status"] in ("queued", "running") for j in jobs):
                recent = self.http("GET", "/api/jobs?recent_seconds=3600")
                failed = [j for j in recent if j["status"] == "failed"]
                if failed:
                    raise SmokeError(f"Tarea fallida: {failed[0]['label']}: {failed[0]['error']}")
                return
            time.sleep(1)
        raise SmokeError("Las tareas no terminaron a tiempo")

    def launcher(self, *args: str) -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "app.launcher", *args],
            cwd=BACKEND, env=self.env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300,
        )  # fmt: skip
        if proc.returncode != 0:
            raise SmokeError(f"launcher {' '.join(args)}: {proc.stdout}{proc.stderr}")
        return proc.stdout.strip()

    def ffmpeg(self) -> str:
        from app.config import load_settings

        os.environ["VSA_HOME"] = str(self.home)
        return load_settings().ffmpeg

    def ffprobe(self, path: Path) -> dict[str, Any]:
        from app.config import load_settings

        out = subprocess.run(
            [load_settings().ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json",
             str(path)], capture_output=True, text=True, encoding="utf-8", check=True,
        )  # fmt: skip
        return dict(json.loads(out.stdout))

    # -- medios sintéticos -------------------------------------------------

    def speech(self, wav: Path) -> str:
        if sys.platform == "darwin" and shutil.which("say"):
            subprocess.run(
                ["say", "-v", "Eddy (Español (España))", "-o", str(wav), "--file-format=WAVE",
                 "--data-format=LEI16@16000", TEXT_ES], check=True,
            )  # fmt: skip
            return "say (macOS)"
        if sys.platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es*' } "
                "| Select-Object -First 1; if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
                "$s.SetOutputToWaveFile($env:VSA_WAV); $s.Speak($env:VSA_TEXT); $s.Dispose(); "
                "if ($v) { 'es' } else { 'default' }"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                env={**os.environ, "VSA_WAV": str(wav), "VSA_TEXT": TEXT_ES},
                capture_output=True, text=True, check=True,
            )  # fmt: skip
            return f"SAPI (Windows, voz {out.stdout.strip()})"
        subprocess.run(
            [self.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=8", "-ar", "16000", "-ac", "1", str(wav)], check=True,
        )  # fmt: skip
        return "tono (sin voz sintética en este sistema)"

    def make_media(self) -> str:
        wav = self.media / "voz.wav"
        voice = self.speech(wav)
        ff = self.ffmpeg()
        for name, size in (("vertical con voz.mp4", "1080x1920"), ("horizontal con voz.mp4", "1920x1080")):
            subprocess.run(
                [ff, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                 f"testsrc2=size={size}:rate=30:duration=9", "-i", str(wav),
                 "-af", "apad", "-t", "9", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                 str(self.media / name)], check=True,
            )  # fmt: skip
        return f"videos sintéticos 9 s con voz: {voice}"

    # -- pasos -------------------------------------------------------------

    def start(self) -> str:
        from tests.fake_anthropic import serve

        self.fake_api, url = serve()
        self.env["VSA_TEST_ANTHROPIC_BASE_URL"] = url
        if self.args.engines_dir:
            src = Path(self.args.engines_dir).resolve()
            self.home.mkdir(parents=True, exist_ok=True)
            link = self.home / "engines"
            try:
                os.symlink(src, link, target_is_directory=True)
            except OSError:
                if sys.platform == "win32":
                    import _winapi

                    _winapi.CreateJunction(str(src), str(link))  # sin privilegios de administrador
                else:
                    raise
        out = self.launcher("start", "--no-browser")
        self.token = (self.home / "run" / "session.token").read_text(encoding="utf-8").strip()
        return out.splitlines()[-1].strip().lstrip("✓ ").strip()

    def session(self) -> str:
        self.http("GET", "/api/projects", token=False, expect=401)
        health = self.http("GET", "/api/health", token=False)
        assert health["edition"] == "community", health
        self.http("GET", "/api/projects")
        return "401 sin token, 200 con token"

    def setup_checks(self) -> str:
        st = self.http("GET", "/api/setup/status")
        bad = [c for c in st["checks"] if c["status"] == "error"]
        if bad:
            raise SmokeError(f"Comprobaciones con error: {bad}")
        self.http("POST", "/api/storage/configure", {"path": str(self.storage)})
        st = self.http("GET", "/api/setup/status")
        assert st["storage_configured"], st
        self.http("POST", "/api/setup/complete", {"completed": True})
        return ", ".join(f"{c['id']}={c['status']}" for c in st["checks"])

    def model(self) -> str:
        models = self.http("GET", "/api/asr/models")
        wanted = self.args.model or models["default_model"]
        m = next(x for x in models["models"] if x["id"] == wanted)
        if not m["installed"]:
            self.http("POST", f"/api/asr/models/{wanted}/download")
            self.wait_jobs(3600)
        prefs = self.http("GET", "/api/settings/analysis")
        self.http("PUT", "/api/settings/analysis", {**prefs, "transcription_model": wanted})
        engines = [e["id"] for e in models["engines"] if e["available"]]
        return f"modelo {wanted} · motores {engines}"

    def engine(self) -> str:
        st = self.http("GET", "/api/animations/engine")
        if not st["browser"]["installed"]:
            self.http("POST", "/api/animations/engine/install")
            self.wait_jobs(1800)
            st = self.http("GET", "/api/animations/engine")
        if not st["ready"]:
            raise SmokeError(f"Motor de animaciones no listo: {st}")
        return f"Remotion {st['remotion']['installed']} · {st['browser']['name']} {st['browser']['version']}"

    def claude(self) -> str:
        self.http("PUT", "/api/claude/api-key", {"key": "sk-ant-test-smoke-0123456789"})
        v = self.http("POST", "/api/claude/verify-key")
        assert v["ok"], v
        t = self.http("POST", "/api/claude/test")
        assert t["ok"] and t["billing"] == "api", t
        return f"clave verificada (sin coste) y prueba ≈ {t['cost_estimate_usd']} USD (API simulada)"

    def project(self, style: str, video: Path, revise: bool) -> str:
        data = video.read_bytes()
        # El mismo video en otro proyecto: la app avisa del duplicado y aquí se permite a propósito.
        q = urllib.parse.urlencode(
            {"filename": video.name, "project_name": f"Smoke {style}", "allow_duplicate": "true"}
        )
        res = self.http("POST", f"/api/imports/upload?{q}", raw=data, timeout=600)
        pid = res["project"]["id"]
        self.wait_jobs()
        self.http("POST", f"/api/projects/{pid}/analyze", {"transcribe": True, "visual": True})
        self.wait_jobs(3600)
        analysis = self.http("GET", f"/api/projects/{pid}/analysis")
        t = analysis["transcript"]
        words = sum(len(s["words"]) for s in t["segments"]) if t else 0
        if not t or t["status"] != "ready" or words < 5:
            raise SmokeError(f"Transcripción sin palabras: {t and t['status']}")
        cfg = self.http("GET", f"/api/projects/{pid}")["config"]
        cfg["style"]["id"] = style
        self.http("PATCH", f"/api/projects/{pid}", {"config": cfg})
        self.http("POST", f"/api/projects/{pid}/plan/generate", {"style": style})
        self.wait_jobs()
        self.http("POST", f"/api/projects/{pid}/plan/bulk", {"status": "accepted"})
        plan = self.http("GET", f"/api/projects/{pid}/plan")["plan"]
        for c in plan["document"]["validation"].get("conflicts") or []:
            self.http("PATCH", f"/api/projects/{pid}/plan/interventions/{c['b']}", {"status": "rejected"})
        self.http("POST", f"/api/projects/{pid}/plan/approve", {})
        self.http("POST", f"/api/projects/{pid}/animations/prepare", {"use_claude": True})
        self.wait_jobs(3600)
        st = self.http("GET", f"/api/projects/{pid}/animations")
        animated = [i for i in st["items"] if i["status"] != "kept"]
        if not animated or any(i["status"] != "ready" for i in animated):
            raise SmokeError(f"Animaciones no listas: {st['items']}")
        sfx = sum(len(i.get("sfx") or []) for i in plan["document"]["interventions"])
        iid = animated[0]["intervention_id"]
        self.http("POST", f"/api/projects/{pid}/animations/{iid}/preview")
        self.wait_jobs()
        extra = ""
        if revise:
            self.http("POST", f"/api/projects/{pid}/scenes/{iid}/revise", {"instruction": "Haz el título más grande"})
            self.wait_jobs()
            sc = self.http("GET", f"/api/projects/{pid}/scenes/{iid}")
            cand = sc["versions"][0]
            if not cand.get("preview"):
                raise SmokeError("La versión candidata no tiene vista previa")
            preview = self.http("GET", cand["preview"]["url"])
            assert isinstance(preview, bytes) and len(preview) > 1000
            self.http("POST", f"/api/projects/{pid}/scenes/{iid}/versions/{cand['number']}/apply", {"confirm": True})
            self.wait_jobs()
            extra = f" · escena regenerada (v{cand['number']})"
        self.http("POST", f"/api/projects/{pid}/exports", {"with_animations": True})
        self.wait_jobs(3600)
        ex = self.http("GET", f"/api/projects/{pid}/exports")[0]
        if ex["status"] != "succeeded" or not ex["settings"]["verification"]["ok"]:
            raise SmokeError(f"Exportación no verificada: {ex}")
        out = self.storage / ex["file_rel"]
        info = self.ffprobe(out)
        src = self.ffprobe(video)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        sv = next(s for s in src["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (sv["width"], sv["height"]), (v, sv)
        assert any(s["codec_type"] == "audio" for s in info["streams"])
        tags = json.dumps(info["format"].get("tags") or {}).lower()
        assert "gabo" not in tags and "video studio" not in tags, tags  # sin marcas en el archivo
        self.projects.append((pid, ex["file_rel"]))
        return (
            f"{style}: {words} palabras ({t['engine']}), {len(animated)} animaciones, {sfx} efectos "
            f"de sonido, vista previa, exportación {v['width']}x{v['height']} verificada{extra}"
        )

    def restart(self) -> str:
        self.launcher("restart", "--no-browser")
        ids = {p["id"] for p in self.http("GET", "/api/projects")}
        missing = [pid for pid, _ in self.projects if pid not in ids]
        if missing:
            raise SmokeError(f"Proyectos perdidos tras reiniciar: {missing}")
        for _, rel in self.projects:
            assert (self.storage / rel).is_file(), rel
        return f"{len(self.projects)} proyectos y exportaciones persisten tras reiniciar"

    def stop(self) -> str:
        """Cierre con trabajo en curso: un análisis de 60 s con FFmpeg y el motor de
        transcripción activos. Ningún proceso del árbol del servidor debe sobrevivir."""
        import psutil

        long_video = self.media / "largo 60s.mp4"
        subprocess.run(
            [self.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
             "testsrc2=size=1920x1080:rate=30:duration=60", "-f", "lavfi", "-i",
             "sine=frequency=300:duration=60", "-c:v", "libx264", "-preset", "ultrafast",
             "-c:a", "aac", "-shortest", str(long_video)], check=True,
        )  # fmt: skip
        q = urllib.parse.urlencode({"filename": long_video.name, "project_name": "Smoke cierre"})
        res = self.http("POST", f"/api/imports/upload?{q}", raw=long_video.read_bytes(), timeout=600)
        self.wait_jobs()
        pid = res["project"]["id"]
        self.http("POST", f"/api/projects/{pid}/analyze", {"transcribe": True, "visual": True})
        inst = json.loads((self.home / "run" / "instance.json").read_text(encoding="utf-8"))
        server = psutil.Process(inst["pid"])
        deadline = time.monotonic() + 60
        tree: list[psutil.Process] = []
        while time.monotonic() < deadline:
            tree = server.children(recursive=True)
            if tree:
                break
            time.sleep(0.2)
        if not tree:
            raise SmokeError("No se observaron procesos hijos durante el análisis")
        names = sorted({p.name() for p in tree if p.is_running()})
        self.launcher("stop")
        time.sleep(1)
        alive = [
            p.pid for p in [server, *tree]
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE
        ]  # fmt: skip
        if alive:
            raise SmokeError(f"Procesos vivos tras cerrar: {alive}")
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", self.port)) == 0:
                raise SmokeError("El puerto sigue abierto tras cerrar")
        # Al volver a abrir, la tarea interrumpida queda registrada (no se ejecuta sola).
        self.launcher("start", "--no-browser")
        jobs = self.http("GET", "/api/jobs?recent_seconds=3600")
        self.launcher("stop")
        states = sorted({j["status"] for j in jobs if j.get("project_id") == pid})
        return (
            f"cerrado con {len(tree)} procesos hijos activos ({', '.join(names)}): ninguno quedó "
            f"vivo; puerto libre; tareas del proyecto tras reabrir: {states}"
        )

    def run(self) -> int:
        self.projects: list[tuple[str, str]] = []
        styles = self.args.styles.split(",")
        try:
            self.step("Videos sintéticos", self.make_media)
            self.step("Arranque con el lanzador", self.start)
            self.step("Token de sesión", self.session)
            self.step("Primera configuración", self.setup_checks)
            self.step("Modelo de transcripción", self.model)
            self.step("Motor de animaciones", self.engine)
            self.step("Conexión con Claude (API simulada)", self.claude)
            for k, style in enumerate(styles):
                video = self.media / ("horizontal con voz.mp4" if style == "minimal_motion" else "vertical con voz.mp4")
                self.step(f"Flujo completo · {style}", lambda s=style, v=video, r=(k == 0): self.project(s, v, r))
            self.step("Reinicio y persistencia", self.restart)
            self.step("Cierre con tareas en curso, sin procesos huérfanos", self.stop)
        except Exception:
            with contextlib.suppress(Exception):
                self.launcher("stop")
        finally:
            if self.fake_api:
                self.fake_api.shutdown()
        ok = all(r["ok"] for r in self.results) and len(self.results) >= 9
        report = {
            "ok": ok,
            "platform": {"system": platform.platform(), "machine": platform.machine(),
                         "python": platform.python_version()},
            "data_dir": str(self.base),
            "steps": self.results,
        }  # fmt: skip
        if self.args.report:
            Path(self.args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n{'✓ TODO CORRECTO' if ok else '✗ HUBO FALLOS'} · {sum(r['ok'] for r in self.results)}/{len(self.results)} pasos")
        if not self.args.keep:
            shutil.rmtree(self.base, ignore_errors=True)
        else:
            print(f"Datos de la prueba conservados en {self.base}")
        return 0 if ok else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser()
    parser.add_argument("--report")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--models-dir")
    parser.add_argument("--engines-dir")
    parser.add_argument("--styles", default=",".join(STYLES))
    return Smoke(parser.parse_args()).run()


if __name__ == "__main__":
    sys.exit(main())
