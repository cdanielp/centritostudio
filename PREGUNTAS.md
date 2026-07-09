# Preguntas y Decisiones Pendientes

## Para validar con el usuario

### 1. Modelo Whisper: ¿small o medium?
- **Situacion actual:** Se usa `small` en GPU (ya cacheado, 3.8s/video de 15s)
- **Medium:** Mas preciso para acentos y vocabulario tecnico, pero requiere descargar ~1.5GB y el primer arranque falla si Windows no tiene Developer Mode activado (symlink issue con HuggingFace Hub)
- **Pregunta:** ¿Prefiere activar Developer Mode en Windows para permitir symlinks y usar `medium`? O ¿`small` es suficiente para tu caso de uso?
- **Fix si quiere medium:** Activar Developer Mode en Windows Settings → Update & Security → For Developers, o correr Python como admin una sola vez para descargar el modelo

### 2. Posicion vertical del texto
- Actualmente: 10-12% desde abajo del frame (configurable por `margin_pct` en cada estilo)
- ¿Quieres captions mas centrados (50%) o mas abajo (8-10%)?

### 3. Numero de palabras por grupo
- Actualmente: max 18 caracteres/linea, 2 lineas max
- CapCut/Captions.ai tipicamente usa 1-3 palabras a la vez (no 4-6 como ahora)
- ¿Prefiere estilo "una palabra a la vez" o "grupo de palabras" (actual)?

### 4. Fuente del estilo hormozi
- Actualmente usa `Arial Black` (disponible en Windows por defecto)
- El estilo original de Hormozi usa "The Bold Font" (gratuita) o "Montserrat ExtraBold"
- ¿Quieres instalar "The Bold Font" para el look mas autentico?
  - Descarga: https://www.theboldguy.co/ (gratuita para uso personal)
  - Luego editar `styles.py`: `font_name="TheBoldFont-Regular"`

### 5. Referencia Captions AI para benchmark (Regla #13)
El archivo `revision/benchmark/referencia_captions.mp4` no existe todavía. Para activar el
benchmark permanente contra Captions AI:
1. Procesa `input/tacosjuan.mp4` con Captions AI y guarda el output como
   `revision/benchmark/referencia_captions.mp4`
2. Los benchmarks de Fase 2 son comparaciones CON vs SIN énfasis IA (no contra la referencia
   externa, que se activa en cuanto el archivo exista).

### 6. Keywords de calidad baja — ajuste del prompt
DeepSeek marcó "muy" (adverbio) y "fue" (verbo auxiliar) como keywords en tacosjuan.
Posible mejora: añadir al prompt "NUNCA adverbios de intensidad (muy, bastante, super)" y
"NUNCA verbos auxiliares (fue, era, está)". Dejar para Fase 2 v2 si el usuario quiere ajustar.

## Decisiones que tome (asumiendolas razonables)

- Primera corrida lenta (181s) fue por descarga del modelo + warmup de CUDA — las corridas subsiguientes son 4x tiempo real (~3.8s para 15s de video)
- La variable `HF_HUB_DISABLE_SYMLINKS_WARNING=1` debe setearse antes de correr (o agregar al `.env`)
- El modelo medium falla en la descarga por permisos de symlinks en Windows sin Developer Mode — se usa small como fallback estable
- Audio de test generado con `es-MX-JorgeNeural` (voz masculina, Mexico). Whisper lo detecta correctamente como `es`

### 7. app.py supera 400 lineas (deuda tecnica)
- **Situacion:** app.py tiene 423 lineas (limite=400 segun reglas centrito-dev).
- **Causa:** acumulacion de endpoints a traves de sesiones; este sesion aniadio ~15 lineas.
- **Fix sugerido:** extraer las funciones background (_run_transcribe, _run_analyze, _run_depurar, _run_render) a un modulo separado `jobs.py`, dejando app.py solo con las rutas FastAPI (~250 lineas).
- **Cuando:** al inicio de Fase 4 (antes de anadir el clipper) para no romper el limite mas.

### 8. Umbrales de diagnostico _eval_joins — RESUELTO
- **Decision del arquitecto:** el loop de ajuste fue eliminado. La medicion voz-a-voz queda
  como diagnostico puro: DELTA_CLEAN_DB = 6, DELTA_NOTABLE_DB = 15.
- **Estado:** implementado. "Threshold irrelevante — el ajuste se elimino; la medicion quedo
  como diagnostico con umbrales 6/15dB." Ver depurador.py.
