"""Almacén seguro de la clave de API del usuario, según el sistema.

- **macOS:** llavero del usuario, con la herramienta ``security`` (validado).
- **Windows:** Administrador de credenciales de Windows (credencial genérica cifrada con DPAPI
  para la cuenta del usuario), a través de ``keyring``.
- **Linux:** Secret Service (GNOME Keyring o KWallet), a través de ``keyring``.
- **Pruebas** (``VSA_ENV=test``): un archivo dentro del directorio de datos de pruebas, para no
  tocar nunca el llavero real del usuario.

La clave nunca se guarda en el navegador, en la base de datos, en los registros ni en los
archivos del proyecto. El servicio es propio de la edición (``edition.KEYCHAIN_SERVICE``): esta
copia nunca lee las credenciales de otra instalación de Video Studio AI.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app import edition
from app.platform.detect import os_id

ACCOUNT = "anthropic-api-key"


class CredentialError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Store(Protocol):
    label: str

    def get(self) -> str | None: ...
    def has(self) -> bool: ...
    def set(self, secret: str) -> None: ...
    def delete(self) -> None: ...


def _service() -> str:
    # Las pruebas nunca comparten servicio con la instalación real.
    if os.environ.get("VSA_ENV") == "test":
        return f"{edition.KEYCHAIN_SERVICE}-test"
    return edition.KEYCHAIN_SERVICE


def _check_format(secret: str) -> None:
    # Sin espacios, comillas ni saltos de línea: la clave viaja por stdin a `security -i`.
    if not secret or not secret.replace("-", "").replace("_", "").isalnum():
        raise CredentialError("invalid_key", "Formato de clave no válido.")


@dataclass
class MacKeychain:
    label: str = "Llavero de macOS"

    def _run(self, args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(  # type: ignore[call-overload]
                ["security", *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                **kw,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CredentialError(
                "keychain_unavailable", "El llavero del sistema no está disponible."
            ) from exc

    def get(self) -> str | None:
        with contextlib.suppress(CredentialError):
            out = self._run(["find-generic-password", "-s", _service(), "-a", ACCOUNT, "-w"])
            key = out.stdout.strip()
            return key if out.returncode == 0 and key else None
        return None

    def has(self) -> bool:
        # Comprueba que existe sin leer el secreto.
        with contextlib.suppress(CredentialError):
            out = self._run(["find-generic-password", "-s", _service(), "-a", ACCOUNT])
            return out.returncode == 0
        return False

    def set(self, secret: str) -> None:
        _check_format(secret)
        # Por stdin (modo interactivo de `security`): nunca visible en la lista de procesos.
        command = f"add-generic-password -U -s {_service()} -a {ACCOUNT} -w {secret}\n"
        out = self._run(["-i"], input=command)
        if out.returncode != 0:
            raise CredentialError("keychain", "No se pudo guardar la clave en el llavero de macOS.")

    def delete(self) -> None:
        self._run(["delete-generic-password", "-s", _service(), "-a", ACCOUNT])


@dataclass
class KeyringStore:
    """Administrador de credenciales de Windows o Secret Service de Linux."""

    label: str

    def _keyring(self) -> Any:
        try:
            import keyring
            from keyring.backends import fail
        except ImportError as exc:
            raise CredentialError(
                "keychain_unavailable",
                "Falta el componente del llavero del sistema. Ejecuta el instalador de nuevo.",
            ) from exc
        if isinstance(keyring.get_keyring(), fail.Keyring):
            raise CredentialError(
                "keychain_unavailable",
                "No hay un llavero del sistema disponible en este equipo"
                + (" (instala GNOME Keyring o KWallet)." if os_id() == "linux" else "."),
            )
        return keyring

    def get(self) -> str | None:
        with contextlib.suppress(Exception):
            value = self._keyring().get_password(_service(), ACCOUNT)
            return value or None
        return None

    def has(self) -> bool:
        return self.get() is not None

    def set(self, secret: str) -> None:
        _check_format(secret)
        kr = self._keyring()
        try:
            kr.set_password(_service(), ACCOUNT, secret)
        except Exception as exc:
            raise CredentialError(
                "keychain", f"No se pudo guardar la clave en {self.label}: {type(exc).__name__}"
            ) from exc

    def delete(self) -> None:
        kr = self._keyring()
        with contextlib.suppress(Exception):
            kr.delete_password(_service(), ACCOUNT)


@dataclass
class TestFileStore:
    """Solo para pruebas automáticas: archivo en el directorio de datos de pruebas."""

    label: str = "Almacén de pruebas"

    def _path(self) -> Path:
        home = Path(os.environ.get("VSA_HOME", "."))
        return home / "test-credentials.json"

    def get(self) -> str | None:
        with contextlib.suppress(OSError, ValueError):
            value = json.loads(self._path().read_text(encoding="utf-8")).get(ACCOUNT)
            return str(value) if value else None
        return None

    def has(self) -> bool:
        return self.get() is not None

    def set(self, secret: str) -> None:
        _check_format(secret)
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({ACCOUNT: secret}), encoding="utf-8")
        with contextlib.suppress(OSError):
            path.chmod(0o600)

    def delete(self) -> None:
        self._path().unlink(missing_ok=True)


def store() -> Store:
    if os.environ.get("VSA_ENV") == "test" and os.environ.get("VSA_TEST_REAL_KEYCHAIN") != "1":
        return TestFileStore()
    system = os_id()
    if system == "macos":
        return MacKeychain()
    if system == "windows":
        return KeyringStore("el Administrador de credenciales de Windows")
    return KeyringStore("el llavero del sistema")
