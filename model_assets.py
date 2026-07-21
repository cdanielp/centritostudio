"""model_assets.py — Especificacion UNICA de los modelos de deteccion facial (H3).

Fuente de verdad para: ruta relativa esperada, detector, si es obligatorio/opcional, URL oficial
verificada y SHA256 esperado. La usan `system_preflight` (diagnostico), `reframe_detect` (mensajes
accionables) y `scripts/setup_models.py` (instalacion reproducible).

Las URLs y los hashes se verificaron durante H3 descargando cada archivo desde su origen oficial
y comprobando que el SHA256 coincide EXACTO con el modelo que ya funciona en el proyecto
(evidencia en `revision/pre-hyperframes/H3_EVIDENCIA.md`). No se inventaron URLs ni hashes.

Los modelos NO se versionan (gitignored) y NO se descargan automaticamente al arrancar el Studio:
la descarga es un paso EXPLICITO (`venv\\Scripts\\python.exe scripts\\setup_models.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ModelAsset:
    """Contrato inmutable de un modelo de deteccion facial."""

    id: str
    rel_path: str  # ruta RELATIVA a la raiz del proyecto (nunca absoluta en mensajes publicos)
    detector: str  # 'yunet' | 'blazeface'
    required: bool  # obligatorio para que exista AL MENOS un detector funcional
    url: str  # URL oficial verificada (HTTPS)
    sha256: str  # hash esperado del binario oficial
    size_bytes: int  # tamano esperado (limite de descarga = size * margen)
    install_hint: str  # instruccion humana de instalacion

    def path(self, root: Path = ROOT) -> Path:
        """Ruta absoluta local (uso interno; NUNCA se expone en mensajes publicos)."""
        return root / self.rel_path


# YuNet es el detector por defecto (reframe 9:16). BlazeFace short-range es el fallback.
# Con CUALQUIERA de los dos el reframe funciona; por eso ambos se marcan required=True solo
# en el sentido de "se necesita al menos uno" (lo resuelve system_preflight, no un booleano suelto).
YUNET = ModelAsset(
    id="yunet",
    rel_path="referencia/yunet/face_detection_yunet_2023mar.onnx",
    detector="yunet",
    required=True,
    url=(
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/"
        "models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    size_bytes=232589,
    install_hint="venv\\Scripts\\python.exe scripts\\setup_models.py --model yunet",
)

BLAZEFACE_SHORT = ModelAsset(
    id="blazeface",
    rel_path="models/blaze_face_short_range.tflite",
    detector="blazeface",
    required=True,
    url=(
        "https://storage.googleapis.com/mediapipe-models/face_detector/"
        "blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
    ),
    sha256="b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f",
    size_bytes=229746,
    install_hint="venv\\Scripts\\python.exe scripts\\setup_models.py --model blazeface",
)

# Orden estable: primero el default (yunet), luego el fallback.
MODELS: tuple[ModelAsset, ...] = (YUNET, BLAZEFACE_SHORT)


def by_id(model_id: str) -> ModelAsset:
    """Devuelve el ModelAsset por id. Lanza KeyError si no existe."""
    for m in MODELS:
        if m.id == model_id:
            return m
    raise KeyError(model_id)


def model_present(asset: ModelAsset, root: Path = ROOT) -> bool:
    """True si el binario existe, es regular y no esta vacio (no valida hash aqui)."""
    p = asset.path(root)
    try:
        return p.is_file() and p.stat().st_size > 0
    except OSError:
        return False


__all__ = ["ModelAsset", "YUNET", "BLAZEFACE_SHORT", "MODELS", "by_id", "model_present"]
