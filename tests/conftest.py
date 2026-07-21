"""Fixtures compartidos. Ningun test de esta suite necesita GPU ni red."""

from pathlib import Path

import pytest


def words_con_procedencia(
    video_path: Path, base: dict, *, lang: str = "es", model: str = "auto"
) -> dict:
    """Sella la procedencia classic H2 en un dict de words (para reuso de _asegurar_transcript).

    Los tests de orquestacion escriben `{name}_words.json` y esperan REUSO sin retranscribir. Con
    P2-CLASSIC-REUSE el reuso exige procedencia del video EXACTO; este helper la agrega desde el
    `stat()` real del video (que ya debe existir en el fixture)."""
    import auto_classic_provenance as acp  # noqa: PLC0415

    return {
        **base,
        "auto_classic_provenance": acp.build_provenance(video_path, lang=lang, model=model),
    }


@pytest.fixture
def ffprobe_ok(monkeypatch):
    """Stub de ffprobe que declara un video valido (1 stream de video, duracion 3s).

    H2 (P1-OUT-3): los predicados de resume usan `media_integrity.video_reanudable` (ffprobe
    real). Los tests de ORQUESTACION que usan MP4 sinteticos no-vacios como "renders validos"
    activan este stub para que esos archivos cuenten como publicables sin FFmpeg; la validacion
    real de 0-byte/truncado/sin-stream vive en `test_h2_resume_integrity.py`. Mantiene REALES los
    chequeos de `is_file()` y `st_size > 0` (un archivo faltante o 0-byte sigue fallando).
    """
    payload = {
        "streams": [{"codec_type": "video", "duration": "3.0"}],
        "format": {"duration": "3.0"},
    }

    import media_integrity  # noqa: PLC0415

    # Se parchea `_ffprobe` (no `subprocess.run`): `media_integrity.subprocess` ES el modulo global,
    # asi que parchear su `.run` clobbea el ffmpeg REAL de otros fixtures (p.ej. e2e). Parchear el
    # helper deja REALES `is_file()`/`st_size>0` y no toca el subprocess global.
    monkeypatch.setattr(media_integrity, "_ffprobe", lambda _p: payload)
    return payload


@pytest.fixture
def transcript_falso():
    """Words en formato {"w", "s", "e", "prob"} para ejercitar group_words.

    Gap de 1.0s entre 'rapido.' (end 2.10) y 'Ahora' (start 3.10) > 0.4s.
    Contiene acento (rapido), enie (nino) y 7 palabras en total.
    """
    return [
        {"w": "El", "s": 0.00, "e": 0.20, "prob": 0.99},
        {"w": "niño", "s": 0.25, "e": 0.60, "prob": 0.98},
        {"w": "aprende", "s": 0.65, "e": 1.20, "prob": 0.99},
        {"w": "rápido.", "s": 1.25, "e": 2.10, "prob": 0.97},
        {"w": "Ahora", "s": 3.10, "e": 3.50, "prob": 0.99},
        {"w": "sí", "s": 3.55, "e": 3.80, "prob": 0.99},
        {"w": "va", "s": 3.85, "e": 5.00, "prob": 0.95},
    ]
