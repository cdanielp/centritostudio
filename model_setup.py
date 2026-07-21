"""model_setup.py — Instalacion reproducible y verificada de los modelos de deteccion (H3).

Cierra P1-BOOT-2: en un clone limpio no habia forma reproducible de instalar YuNet/BlazeFace.
Cada modelo se descarga desde su URL OFICIAL (verificada en H3), se valida por SHA256 y se publica
de forma ATOMICA (`os.replace`), preservando cualquier modelo anterior ante fallo.

Reglas de seguridad:
  - Solo esquemas http/https (los redirects a esquemas no-web se rechazan).
  - Timeout de conexion/lectura.
  - Limite DURO de bytes (rechaza un cuerpo mas grande que el esperado + margen).
  - SHA256 obligatorio: un hash distinto NO se escribe (el modelo anterior queda intacto).
  - Nunca se ejecuta red al importar el modulo ni al arrancar el Studio: solo dentro de
    `install_model`, que se invoca EXPLICITAMENTE desde `scripts/setup_models.py`.

La logica de red esta aislada en `_fetch`, inyectable para tests deterministas sin red.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError

import model_assets
from model_assets import ROOT, ModelAsset

DEFAULT_TIMEOUT_S = 30.0
SIZE_MARGIN = 1.10  # se acepta hasta 10% mas que el tamano esperado antes de abortar
_CHUNK = 1 << 16


class ModelSetupError(Exception):
    """La instalacion de un modelo no pudo completarse de forma verificable."""


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Rechaza redirects a esquemas que no sean http/https (p.ej. file://, ftp://)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in ("http", "https"):
            raise ModelSetupError("redirect a un esquema no permitido")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch(url: str, *, timeout: float, max_bytes: int) -> bytes:
    """Descarga `url` con timeout y tope DURO de bytes. Solo http/https. Inyectable en tests."""
    scheme = url.split(":", 1)[0].lower()
    if scheme not in ("http", "https"):
        raise ModelSetupError("esquema de URL no permitido")
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    req = urllib.request.Request(url, headers={"User-Agent": "centrito-setup-models"})
    buf = bytearray()
    try:
        with opener.open(req, timeout=timeout) as resp:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > max_bytes:
                    raise ModelSetupError("la descarga excede el tamano esperado")
    except (URLError, TimeoutError, OSError) as exc:
        raise ModelSetupError(f"no se pudo descargar el modelo ({type(exc).__name__})") from None
    return bytes(buf)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def publish_bytes(dest: Path, data: bytes) -> None:
    """Escribe `data` a un temporal en el mismo dir y publica con `os.replace` (atomico).

    Ante cualquier fallo borra el temporal; un `dest` anterior queda intacto (nunca a medias).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{uuid.uuid4().hex}.part"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise ModelSetupError("no se pudo publicar el modelo") from None


def install_model(
    asset: ModelAsset,
    *,
    fetch: Callable[..., bytes] = _fetch,
    root: Path = ROOT,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Path:
    """Descarga, verifica por SHA256 y publica un modelo. Devuelve la ruta destino.

    Un hash distinto NO se escribe (ModelSetupError) -> el modelo anterior se preserva.
    """
    dest = asset.path(root)
    max_bytes = int(asset.size_bytes * SIZE_MARGIN)
    data = fetch(asset.url, timeout=timeout, max_bytes=max_bytes)
    got = _sha256(data)
    if got != asset.sha256:
        raise ModelSetupError(
            f"hash del modelo {asset.id} no coincide (esperado {asset.sha256[:12]}..., "
            f"obtenido {got[:12]}...); no se escribio nada"
        )
    publish_bytes(dest, data)
    return dest


def install_all(
    ids: list[str] | None = None,
    *,
    fetch: Callable[..., bytes] = _fetch,
    root: Path = ROOT,
    force: bool = False,
) -> list[tuple[str, str]]:
    """Instala los modelos pedidos (por defecto todos los usados). Devuelve [(id, resultado)].

    No descarga un modelo ya presente salvo `force=True` (evita red innecesaria y no baja
    modelos no utilizados). `resultado` in {"ok", "ya-presente", "error: ..."}.
    """
    seleccion = model_assets.MODELS if not ids else [model_assets.by_id(i) for i in ids]
    resultados: list[tuple[str, str]] = []
    for asset in seleccion:
        if not force and model_assets.model_present(asset, root):
            resultados.append((asset.id, "ya-presente"))
            continue
        try:
            install_model(asset, fetch=fetch, root=root)
            resultados.append((asset.id, "ok"))
        except ModelSetupError as exc:
            resultados.append((asset.id, f"error: {exc}"))
    return resultados


__all__ = [
    "ModelSetupError",
    "install_model",
    "install_all",
    "publish_bytes",
    "DEFAULT_TIMEOUT_S",
    "SIZE_MARGIN",
]
