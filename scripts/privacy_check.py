#!/usr/bin/env python3
"""Comprobación de privacidad antes de cada commit o publicación.

  python3 scripts/privacy_check.py --staged   # archivos preparados para el commit (hook)
  python3 scripts/privacy_check.py --all      # todos los archivos versionados

Bloquea:
- medios, bases de datos, registros, claves y archivos de entorno;
- binarios no permitidos;
- rutas absolutas de usuario (macOS/Windows) y de volúmenes externos;
- correos electrónicos (salvo los avisos de licencia de terceros);
- claves de API y tokens con forma conocida;
- términos privados del mantenedor listados en `.privacy-terms.local` (no versionado).
Si `gitleaks` está instalado, también lo ejecuta sobre lo preparado.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_TYPES = re.compile(
    r"\.(mp4|mov|m4a|wav|mp3|aac|mkv|webm|avi|db|sqlite3?|db-wal|db-shm|log|env|pem|key|p12|pfx|npz|safetensors|bin|gguf)$",
    re.I,
)
ALLOWED_BINARIES = re.compile(r"\.(ttf|otf|woff2?|onnx|svg|ico|png)$", re.I)
LICENSE_FILE = re.compile(r"(^|/)(LICENSE[^/]*|licenses/[^/]+|THIRD_PARTY_NOTICES\.md)$", re.I)
PATTERNS = [
    (re.compile(r"/Users/(?!tu-usuario/|usuario/|<|\.\.\.)[A-Za-z0-9._-]+/"), "ruta de usuario de macOS"),
    (re.compile(r"[A-Za-z]:\\\\{1,2}Users\\\\{1,2}(?!usuario|<)[^\\\s\"']+"), "ruta de usuario de Windows"),
    (re.compile(r"/Volumes/(?!MiDisco\b|Disco\b|__vsa_|<|…)[^/\s\"'`]+"), "ruta de un volumen externo"),
    (re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.|users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "correo electrónico"),
    # «sk-ant-test-…» está reservado a claves ficticias de las pruebas (ninguna clave real de
    # Anthropic empieza así: api03, admin01, oat01…). Cualquier otra forma se bloquea.
    (re.compile(r"sk-ant-(?!test-)[A-Za-z0-9_-]{16,}"), "clave de API de Anthropic"),
    (re.compile(r"(ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}"), "token de GitHub"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "clave de AWS"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "clave privada"),
    (re.compile(r"hf_[A-Za-z0-9]{30,}"), "token de Hugging Face"),
]
EMAIL_OK = {"community@video-studio-ai.invalid"}


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout


def files(staged: bool) -> list[str]:
    out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR") if staged else git("ls-files")
    return [f for f in out.splitlines() if f]


def content(path: str, staged: bool) -> bytes:
    if staged:
        return subprocess.run(["git", "-C", str(ROOT), "show", f":{path}"], check=True, capture_output=True).stdout
    return (ROOT / path).read_bytes()


def private_terms() -> list[str]:
    f = ROOT / ".privacy-terms.local"
    if not f.is_file():
        return []
    return [t.strip() for t in f.read_text().splitlines() if t.strip() and not t.startswith("#")]


def check(path: str, data: bytes, terms: list[str]) -> list[str]:
    found: list[str] = []
    if path == "scripts/privacy_check.py":
        return found  # contiene los propios patrones
    if BLOCKED_TYPES.search(path):
        found.append("tipo de archivo no permitido (medios, datos, registros o claves)")
    binary = b"\0" in data[:8192]
    if binary and not ALLOWED_BINARIES.search(path):
        found.append("binario no permitido")
    text = data.decode("latin-1" if binary else "utf-8", errors="ignore")
    low = text.lower()
    found += [f"término privado n.º {i + 1}" for i, t in enumerate(terms) if t.lower() in low]
    if binary:
        return found
    for rx, what in PATTERNS:
        for m in rx.finditer(text):
            if what == "correo electrónico" and (m.group(0) in EMAIL_OK or LICENSE_FILE.search(path)):
                continue
            found.append(what)
            break
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true")
    g.add_argument("--all", action="store_true")
    a = ap.parse_args()
    terms = private_terms()
    problems = []
    for f in files(a.staged):
        try:
            data = content(f, a.staged)
        except (OSError, subprocess.CalledProcessError):
            continue
        hits = check(f, data, terms)
        if hits:
            problems.append((f, sorted(set(hits))))
    gitleaks = shutil.which("gitleaks")
    if gitleaks:
        mode = ["git", "--staged"] if a.staged else ["git"]
        r = subprocess.run([gitleaks, *mode, "--redact", "--no-banner", str(ROOT)], capture_output=True, text=True)
        if r.returncode not in (0,):
            problems.append(("(gitleaks)", ["posibles secretos detectados: ejecuta gitleaks para ver el detalle"]))
    if problems:
        print("Comprobación de privacidad: BLOQUEADO", file=sys.stderr)
        for f, hits in problems:
            print(f"  {f}: {', '.join(hits)}", file=sys.stderr)
        print("Corrige o excluye esos archivos antes de continuar.", file=sys.stderr)
        return 1
    scope = "preparados" if a.staged else "versionados"
    extra = " + gitleaks" if gitleaks else " (gitleaks no instalado: solo patrones propios)"
    print(f"Comprobación de privacidad correcta: {len(files(a.staged))} archivos {scope}{extra}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
