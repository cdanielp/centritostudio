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

## Decisiones que tome (asumiendolas razonables)

- Primera corrida lenta (181s) fue por descarga del modelo + warmup de CUDA — las corridas subsiguientes son 4x tiempo real (~3.8s para 15s de video)
- La variable `HF_HUB_DISABLE_SYMLINKS_WARNING=1` debe setearse antes de correr (o agregar al `.env`)
- El modelo medium falla en la descarga por permisos de symlinks en Windows sin Developer Mode — se usa small como fallback estable
- Audio de test generado con `es-MX-JorgeNeural` (voz masculina, Mexico). Whisper lo detecta correctamente como `es`
