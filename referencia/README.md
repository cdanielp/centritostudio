# referencia/

Esta carpeta contiene codigo de referencia de terceros estudiado durante el desarrollo.
**No se incluye en el repositorio** (ver `.gitignore`).

## referencia/yunet/

Proyecto de referencia: **missouri-face-track** de Fuskilla.

Contiene:
- `vertical_reframe.py` — implementacion de referencia de reframe vertical con YuNet + waypoints
- `SKILL.md` — documentacion del diseno (cortes-primero, deadzone, SplitIdentityTracker)
- `test_*.py` — tests de contrato del tracker de identidad
- `face_detection_yunet_2023mar.onnx` — modelo YuNet (ONNX)

**Credito:** el diseno del modo escenas (`reframe_escenas.py`) y el detector YuNet adoptado
en sesion 24-25 se basan en este trabajo. La implementacion de Centrito es propia
(reimplementacion, no copia literal).

Para obtener el codigo: contactar a Fuskilla directamente.
