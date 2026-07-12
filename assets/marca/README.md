# assets/marca — Logo de marca (M2, pendiente de K)

Slot para el **logo real** de Prompt Models Studio (PNG con transparencia).

La capa FX (`fx.py`, preset `express`/`premium`) toma automáticamente el **primer `.png`**
de esta carpeta como logo/outro. Si la carpeta está vacía, el FX degrada limpio (sin logo,
el render no se cae).

Reglas:
- **Logo real desde PNG, nunca generado por IA** (guardrail S36-FX).
- Poner UN solo `.png` para evitar ambigüedad (se elige el primero por orden alfabético).
- Colores de marca: morado `#7C3AED`.

Durante el smoke de S36-FX se usó un `logo.png` PLACEHOLDER generado con Pillow (NO commiteado);
el logo definitivo lo aporta K (material M2).
