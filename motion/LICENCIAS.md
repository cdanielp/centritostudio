# Licencias de los assets embebidos en las plantillas de HyperFrames (HF-2)

Cada proyecto de `motion/` es autocontenido: el render debe ser reproducible sin internet,
asi que la fuente y el runtime de animacion viajan como archivos locales dentro de cada
carpeta de plantilla. Nada se carga por red.

## Fuente: Inter (variable)

- Archivo: `motion/<plantilla>/fonts/InterVariable.woff2` (una copia por plantilla)
- Version: 4.x, ejes de peso 100 a 900
- Autor: The Inter Project Authors (https://github.com/rsms/inter)
- Licencia: **SIL Open Font License 1.1** (copia completa en `motion/OFL_Inter.txt`)
- La OFL permite uso, redistribucion y embebido comercial; solo prohibe vender la fuente
  sola. Renderizar video con ella no impone ninguna obligacion sobre el video.

## Runtime de animacion: GSAP

- Archivo: `motion/<plantilla>/gsap.min.js` (una copia por plantilla, version 3.14.2)
- Autor: Webflow / GreenSock
- Licencia: **GSAP Standard License** (gratuita, uso comercial permitido; desde la
  version 3.13 GSAP es 100% gratis, incluidos los plugins). No es OSI, pero permite
  exactamente este uso: redistribuir el archivo sin modificar como parte de un proyecto.

## Colores estructurales fijos (los unicos permitidos por la regla 4 del brief)

Los tres colores de marca (`marca_primario`, `marca_secundario`, `marca_texto`) llegan
por variables del contrato y se inyectan como CSS custom properties. Los unicos valores
fijos en el CSS son estructurales de legibilidad, no de marca:

- `rgba(8, 8, 15, 0.78)` (placa): panel oscuro translucido detras de todo texto, para
  que la pieza se lea sobre screencast claro u oscuro sin depender del fondo.
- `rgba(0, 0, 0, 0.45)` (sombra): sombra de texto y de caja, mismo motivo.

Ambos son negros de estructura: si la marca cambia, ellos no.
