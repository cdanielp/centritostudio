"""Fixtures compartidos. Ningun test de esta suite necesita GPU ni red."""

import pytest


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
