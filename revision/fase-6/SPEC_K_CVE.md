Quiero que F6 no sea un estilo fijo de captions, sino un sistema general llamado `caption_viral_engine`.

Objetivo:
Crear un motor configurable de captions virales para Reels, TikTok, Shorts y clips verticales 9:16. Debe funcionar para podcast, entrevistas, historias, storytelling, contenido educativo, terror, humor, ventas, clips motivacionales, clips de opinión y contenido general.

No debe estar basado en una marca específica. Debe ser libre, configurable y reutilizable para distintos usuarios.

Definición de tipografía cinética para este proyecto:
Texto en pantalla que no solo subtitula, sino que dirige la atención del espectador. Los captions deben ser legibles, dinámicos y sincronizados con la voz. Algunas palabras o frases importantes deben poder animarse con pop, rebote, escala, glow aproximado, shake controlado, swipe, zoom, entrada rápida, subrayados, cajas, círculos, flechas, bursts, imágenes o formas animadas detrás del texto.

La idea no es saturar el video con efectos. La idea es crear captions que se sientan virales, premium, profesionales y útiles para retener atención.

Quiero un sistema parecido a captions virales de Reels/TikTok/Shorts, pero configurable por usuario.

Arquitectura deseada:
Crear un módulo independiente llamado `caption_viral_engine`.

Debe poder:

1. Usar los captions actuales como base.
2. Generar captions virales como modo aparte o capa de orquestación.
3. Activarse o desactivarse por configuración.
4. Permitir que el usuario elija estilo, intensidad, posición, colores, animaciones, imágenes, overlays y palabras destacadas.
5. Detectar automáticamente palabras importantes.
6. Permitir marcado manual de palabras/frases importantes.
7. Tener fallback seguro a captions simples si un efecto falla, no cabe o no es legible.
8. No reescribir motores existentes si ya existen subsistemas útiles; debe componerlos, configurarlos y orquestarlos.

Casos de uso principales:

* Podcast clips.
* Entrevistas.
* Storytelling.
* Historias de terror.
* Clips educativos.
* Clips virales de opinión.
* Contenido motivacional.
* Clips de ventas.
* Narraciones con imágenes.
* Videos con frases fuertes o momentos de impacto.

Requisitos generales:

* Formato principal: vertical 9:16.
* Texto siempre dentro de safe zones.
* Evitar tapar caras importantes cuando exista información de rostro/trayectoria.
* Mantener legibilidad como prioridad.
* Soportar 1–2 líneas de texto cuando sea posible.
* Evitar saturar la pantalla con demasiados efectos simultáneos.
* Permitir estilos premium, virales, limpios, agresivos o minimalistas.
* El primer segundo debe permitir un hook visual fuerte.
* El usuario debe poder configurar el nivel de intensidad.
* Debe existir modo automático y modo manual.
* Si algo falla, el video nunca debe quedar sin captions; debe volver a captions simples.

Modos de intensidad deseados:

1. `minimal`
   Captions limpios, modernos, casi planos, con poco movimiento.

2. `clean`
   Captions profesionales tipo podcast premium, con énfasis leve.

3. `viral`
   Modo recomendado. Pop, rebote controlado, highlights, palabras grandes, formas simples y microanimaciones.

4. `high_energy`
   Más dopamina visual: zooms, shakes, bursts, stickers, imágenes y cambios de posición.

5. `experimental`
   Glitch, profundidad, chromatic aberration, text takeover, animaciones más agresivas y efectos especiales.

Para v1, priorizar `minimal`, `clean` y `viral`. Dejar `high_energy` y `experimental` especificados como backlog si no caben bien en esta fase.

Presets iniciales deseados:

1. `clean_podcast`
   Captions grandes, limpios, profesionales, ideales para entrevistas y podcast.

2. `premium_flat`
   Texto plano, elegante, con transiciones suaves y estética premium minimalista.

3. `viral_bounce`
   Captions con rebote controlado, pop, escala y énfasis en palabras clave.

4. `karaoke_highlight`
   Texto sincronizado palabra por palabra, con highlight progresivo estilo karaoke moderno.

5. `keyword_punch`
   Palabras importantes aparecen grandes, con impacto visual, pop fuerte, glow aproximado, shake leve o burst visual.

6. `storytelling_cinematic`
   Frases importantes aparecen como títulos narrativos, con movimiento sobrio y dramático.

7. `glitch_cyber`
   Texto con glitch controlado, scanlines, chromatic aberration y estética digital/tech.

8. `meme_impact`
   Texto grande, directo, con cortes agresivos, zooms y énfasis cómico.

9. `educational_clear`
   Captions claros para explicar ideas, con palabras clave resaltadas, números, listas y etiquetas.

10. `image_popups`
    Captions combinados con imágenes, stickers, screenshots, emojis visuales o elementos gráficos que entren en momentos clave.

11. `hook_takeover`
    Primeros 1–2 segundos con frase gigante dominando pantalla para maximizar retención inicial.

12. `commentary_reactor`
    Estilo para clips de opinión/reacción, con frases fuertes, etiquetas, arrows, callouts y texto dinámico.

Para v1, priorizar:

1. `clean_podcast`
2. `viral_bounce`
3. `karaoke_highlight`
4. `keyword_punch`
5. `image_popups`

Los demás presets pueden quedar especificados como backlog post-v1.

Sistema de detección automática de palabras importantes:
Debe analizar el transcript y detectar, como mínimo:

* Números.
* Porcentajes.
* Dinero.
* Fechas.
* Preguntas.
* Negaciones fuertes.
* Contrastes como "pero", "aunque", "sin embargo".
* Palabras repetidas.
* Frases que puedan funcionar como hook.
* Frases emocionales.
* Momentos de giro en una historia.
* Palabras o frases que puedan funcionar como título visual.

Para v1, puede ser una detección determinista con regex y heurísticas. Si existe un `brain.json` previo con hooks, frases emocionales o momentos importantes, puede usarse como enriquecimiento opcional, sin depender de nuevas llamadas LLM.

Sistema manual:
El usuario debe poder marcar manualmente palabras o frases con una sintaxis simple.

Para v1, aceptar como mínimo:

* `[strong]esto cambió todo[/strong]`
* `[big]10 millones[/big]`
* `[center]la frase principal[/center]`

También quiero timestamps manuales para imágenes/overlays.

Ejemplos deseados a futuro:

* `[shake]nadie lo esperaba[/shake]`
* `[image:foto1]cuando mencione esto[/image]`
* `[glitch]error fatal[/glitch]`

La regla importante:
Si una marca manual es inválida, debe tratarse como texto plano. Nunca debe romper render, captions ni export.

Sistema de imágenes y overlays:
El sistema debe permitir que el usuario agregue imágenes, stickers, screenshots, emojis visuales, iconos, formas, flechas, círculos, cajas, subrayados o fondos detrás del texto.

Las imágenes deben poder venir de una biblioteca del usuario, no solamente de generación automática.

Las imágenes deben poder entrar:

* Al inicio del clip.
* Al mencionar una palabra clave.
* Al detectar una entidad.
* En un timestamp manual.
* Como popup lateral.
* Como imagen centrada.
* Como fondo temporal.
* Como sticker pequeño.
* Como callout al lado del caption.
* Como pantalla dividida.
* Como transición visual entre frases.

Opciones de ubicación:

* `top`
* `center`
* `bottom`
* `left`
* `right`
* `top_left`
* `top_right`
* `bottom_left`
* `bottom_right`
* `auto_safe`
* `avoid_faces`
* `behind_text`
* `full_screen_takeover`

Reglas de composición:

* No tapar caras importantes cuando exista información de rostros/trayectoria.
* No tapar captions principales.
* Mantener safe zones de TikTok/Reels/Shorts.
* Si hay conflicto visual, aplicar fallback en cadena:

  1. Reducir tamaño.
  2. Mover elemento.
  3. Simplificar animación.
  4. Desactivar overlay.
  5. Volver a caption simple.
* Si una imagen no cabe bien, usar fallback a callout pequeño.
* Si el fondo es complejo, usar caja, sombra, stroke o blur aproximado detrás del texto si el motor lo permite.

Configuración que debe exponer al usuario:

* Activar/desactivar `caption_viral_engine`.
* Elegir preset.
* Elegir intensidad.
* Elegir tamaño de fuente.
* Elegir posición.
* Elegir colores.
* Elegir estilo de animación.
* Elegir si quiere detección automática de keywords.
* Elegir si quiere marcado manual.
* Elegir si permite imágenes/overlays.
* Elegir si permite texto gigante tipo hook.
* Elegir si permite efectos experimentales.
* Elegir si quiere evitar caras.
* Elegir si quiere captions siempre abajo o dinámicos.
* Elegir idioma.
* Elegir si quiere export para Reels/TikTok/Shorts.

Output esperado de F6:

1. Proponer la arquitectura del `caption_viral_engine`.
2. Definir cómo se integra con los captions actuales.
3. Crear los presets reutilizables.
4. Crear sistema de configuración por usuario.
5. Crear sistema de detección automática de palabras importantes.
6. Crear sistema de marcado manual.
7. Crear sistema de imágenes/overlays.
8. Crear reglas de safe zone, legibilidad y fallback.
9. Incluir demo mínima con varios presets.
10. Priorizar estabilidad, legibilidad y modularidad.
11. Dejar especificado qué queda para sesiones Sonnet posteriores.

Prioridad de implementación:
Primero construir:

1. `clean_podcast`
2. `viral_bounce`
3. `karaoke_highlight`
4. `keyword_punch`
5. `image_popups`

Después agregar:
6. `storytelling_cinematic`
7. `premium_flat`
8. `meme_impact`
9. `educational_clear`
10. `glitch_cyber`
11. `hook_takeover`
12. `commentary_reactor`

La idea final:
Un sistema general de captions virales, configurable, reusable y apto para muchos tipos de contenido, donde el usuario pueda elegir cuánto quiere de estilo limpio, viral, premium, dopaminérgico o experimental.
