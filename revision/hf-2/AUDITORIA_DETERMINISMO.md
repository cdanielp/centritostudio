# Auditoria de determinismo del catalogo de HyperFrames (addendum de HF-2)

**Fecha:** 2026-08-04
**HEAD auditado:** `ff016a933150d9a799c482076a28a29f6ae8cbb8` (`ff016a9`, rama base `main`)
**Rama de la auditoria:** `docs/hf2-auditoria-determinismo`
**Alcance:** SOLO LECTURA y medicion. No se reparo nada. No se toco `motion/`, ni la suite, ni
`hyperframes/`. El unico archivo creado en el repo es este.

## Entorno fijado

| Componente | Version | Como se verifico |
|---|---|---|
| HyperFrames | `0.7.90` | `npx --no-install hyperframes --version` desde `C:\CLAUDECODE\hyperframes-lab` |
| Node.js | `v24.18.0` | `node -v` |
| Chromium Headless Shell | `152.0.7928.2` | traza del propio render: `HeadlessChrome/152.0.7928.2` |
| FFmpeg / FFprobe | `8.0-essentials_build-www.gyan.dev` | `ffmpeg -version` |
| GPU de rasterizacion | `ANGLE (NVIDIA GeForce RTX 5070 Ti, D3D11)` | traza del render: `browserGpuMode auto -> hardware` |
| Maquina | Windows 11 Pro 10.0.26200, 16 cores | `workerCount: 2` resuelto por el CLI en modo `auto` |

No se ejecuto `npx hyperframes skills update` ni ningun comando que cambie version o set de skills.

## Metodologia

Los renders de medicion viven FUERA del repo, en `C:\CLAUDECODE\hyperframes-lab\auditoria\`
(arnes `medir.py`, `diferencia.py`, `diff_pixel.py`; salidas en `auditoria/salida/`).

El arnes reutiliza `hyperframes.invocador.construir_comando` y
`hyperframes.invocador.escribir_variables` del repo, de modo que el comando medido es
EXACTAMENTE el que ejecuta produccion, no una aproximacion. `npx` se resuelve con
`shutil.which` (devuelve `npx.CMD`), las variables van por `--variables-file` en UTF-8
explicito y todo corre con `PYTHONDONTWRITEBYTECODE=1`.

Comando exacto de una medicion (hook vertical, corrida 1 del bloque B):

```
C:\Program Files\nodejs\npx.CMD hyperframes render C:\CLAUDECODE\ediciondevideo\motion\hook --format mov --quality high --fps 30 --output C:\CLAUDECODE\hyperframes-lab\auditoria\salida\b\hook_vertical\run1\pieza.mov --variables-file C:\CLAUDECODE\hyperframes-lab\auditoria\salida\b\hook_vertical\run1\pieza-variables.json --no-best-effort
```

Las dos corridas de cada caso escriben en carpetas distintas pero con el MISMO basename
(`pieza.mov`), para que el nombre del archivo no pueda ser la fuente de una diferencia de sha.

---

## BLOQUE A. Auditoria estatica de las 5 plantillas y sus 5 gemelos

Los diez archivos auditados son `motion/{cierre,dato_destacado,hook,lower_third,titulo_seccion}/index.html`
y sus gemelos `.../horizontal/index.html`.

### A1. Fuentes de no determinismo en JS

Comando y salida literal (restringido a los `index.html`, que son la fuente de las plantillas):

```
$ grep -rnE "Math\.random|Date\.now|performance\.now|new Date\(|crypto\.getRandomValues" motion/ --include=*.html
exit=1
```

`exit=1` de grep significa CERO coincidencias en los diez archivos.

El runtime vendorizado `gsap.min.js` si contiene esas primitivas por copia. Comando y salida:

```
$ grep -roE "Math\.random|Date\.now|performance\.now|new Date\(|crypto\.getRandomValues" motion/ --include=gsap.min.js | sort | uniq -c
      2 motion/cierre/gsap.min.js:Date.now
      3 motion/cierre/gsap.min.js:Math.random
      2 motion/dato_destacado/gsap.min.js:Date.now
      3 motion/dato_destacado/gsap.min.js:Math.random
      2 motion/hook/gsap.min.js:Date.now
      3 motion/hook/gsap.min.js:Math.random
      2 motion/lower_third/gsap.min.js:Date.now
      3 motion/lower_third/gsap.min.js:Math.random
      2 motion/titulo_seccion/gsap.min.js:Date.now
      3 motion/titulo_seccion/gsap.min.js:Math.random
```

Contexto de esas cinco ocurrencias (todas en una unica copia; los cinco archivos tienen
sha256 identico `fd6978c80858a3036c39b4e53b5a6f9385d759d43283e6b1de89237e5640d85f`):

```
$ grep -oE ".{90}(Math\.random|Date\.now).{90}" motion/hook/gsap.min.js
...function gb(t){return t.sort(function(){return.5-Math.random()})}...
...function kb(t,e,r,i){return Za($(t)?!e:!0===r?!!(r=0):!i,function(){return $(t)?t[~~(Math.random()*t.length)]...
...Ft=/hsl[a]?\(/,It=(O=Date.now,M=500,C=33,P=O(),A=P,z=D=1e3/240,g={time:0,frame:0,tick:function tick(){Al(!0)}...
...function Ic(){var t=Date.now(),o=[];2<t-Ce&&(Hc("matchMediaInit"),ke.forEach(function(t){var e,r,i,n,a=t.queries...
```

Son el helper de shuffle, `gsap.utils.random`, el ticker y el poll de `matchMedia`. Ninguna
plantilla llama a esas utilidades (ver A4: solo se usa `gsap.timeline`) y el timeline se
recorre por seek, no por ticker, asi que no alcanzan la salida. Queda anotado como superficie.

### A2. `repeat: -1`

```
$ grep -rnE "repeat\s*:\s*['\"]?-\s*1" motion/
exit=1
```

Cero coincidencias, con o sin espacios y comillas. Los diez archivos usan un `repeat`
calculado y finito. Salida literal de todos los `repeat` del catalogo:

```
$ grep -rnE "repeat" motion/ --include=*.html
motion/cierre/horizontal/index.html:137:        tl.to("#respira", { scale: 1.012, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, STAG + ENTRA);
motion/cierre/index.html:137:        tl.to("#respira", { scale: 1.012, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, STAG + ENTRA);
motion/dato_destacado/horizontal/index.html:143:        tl.to("#respira", { scale: 1.01, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/dato_destacado/index.html:143:        tl.to("#respira", { scale: 1.01, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/hook/horizontal/index.html:144:        tl.to("#respira", { scale: 1.008, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/hook/index.html:144:        tl.to("#respira", { scale: 1.008, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/lower_third/horizontal/index.html:133:        tl.to("#respira", { scale: 1.006, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/lower_third/index.html:133:        tl.to("#respira", { scale: 1.006, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/titulo_seccion/horizontal/index.html:131:        tl.to("#respira", { scale: 1.008, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
motion/titulo_seccion/index.html:131:        tl.to("#respira", { scale: 1.008, duration: medio, ease: "sine.inOut", yoyo: true, repeat: reps }, ENTRA);
```

El valor `reps` esta acotado por una guarda que descarta cualquier valor negativo, incluido
`-1` (que en GSAP significa infinito) y `NaN`:

```
$ grep -rnE "var reps|reps -=|reps >=|reps %" motion/hook/index.html
motion/hook/index.html:141:      var reps = Math.floor(resto / medio) - 1;
motion/hook/index.html:142:      if (reps % 2 === 0) reps -= 1;
motion/hook/index.html:143:      if (reps >= 1) {
```

El patron es identico en los diez archivos (lineas 128-136 en cierre, 140-142 en
dato_destacado, 130-132 en lower_third, 128-130 en titulo_seccion).

### A3. Numero de timelines y estado de pausa

```
$ grep -rnE "gsap\.timeline|paused" motion/ --include=*.html
motion/cierre/horizontal/index.html:126:      var tl = gsap.timeline({ paused: true });
motion/cierre/index.html:126:      var tl = gsap.timeline({ paused: true });
motion/dato_destacado/horizontal/index.html:132:      var tl = gsap.timeline({ paused: true });
motion/dato_destacado/index.html:132:      var tl = gsap.timeline({ paused: true });
motion/hook/horizontal/index.html:132:      var tl = gsap.timeline({ paused: true });
motion/hook/index.html:132:      var tl = gsap.timeline({ paused: true });
motion/lower_third/horizontal/index.html:121:      var tl = gsap.timeline({ paused: true });
motion/lower_third/index.html:121:      var tl = gsap.timeline({ paused: true });
motion/titulo_seccion/horizontal/index.html:121:      var tl = gsap.timeline({ paused: true });
motion/titulo_seccion/index.html:121:      var tl = gsap.timeline({ paused: true });
```

Exactamente una ocurrencia por archivo, las diez con `paused: true` explicito. Cero
`paused: false`. Cada archivo publica esa unica timeline y ninguna mas:

```
$ grep -rnE "__timelines" motion/hook/index.html
motion/hook/index.html:131:      window.__timelines = window.__timelines || {};
motion/hook/index.html:148:      window.__timelines["main"] = tl;
```

### A4. `gsap.set` al cargar sobre elementos de escenas posteriores

```
$ grep -rnE "gsap\.set" motion/ --include=*.html
exit=1
```

Cero. De hecho las plantillas solo usan dos simbolos de GSAP en total:

```
$ grep -rhoE "gsap\.[a-zA-Z]+" motion/ --include=*.html | sort | uniq -c
     10 gsap.min
     10 gsap.timeline
```

(`gsap.min` es la coincidencia del `<script src="gsap.min.js">`, no una llamada.)
Ademas, las cinco piezas son de UNA sola escena (`#pieza`, un unico `.clip`), asi que no
existen "escenas posteriores" sobre las que un `set` pudiera adelantarse.

### A5. Tweens sobre `display` o `visibility` crudas

```
$ grep -rnE "display|visibility" motion/ --include=*.html
motion/cierre/horizontal/index.html:43:        display: grid; place-items: center;
motion/cierre/horizontal/index.html:64:        display: inline-block;
motion/cierre/index.html:43:        display: grid; place-items: center;
motion/cierre/index.html:64:        display: inline-block;
motion/dato_destacado/horizontal/index.html:43:        display: grid; place-items: center;
motion/dato_destacado/index.html:43:        display: grid; place-items: center;
motion/hook/horizontal/index.html:47:        display: grid; place-items: center;
motion/hook/horizontal/index.html:59:        display: inline-block;
motion/hook/index.html:47:        display: grid; place-items: center;
motion/hook/index.html:59:        display: inline-block;
motion/lower_third/horizontal/index.html:48:        display: flex;
motion/lower_third/index.html:48:        display: flex;
motion/titulo_seccion/horizontal/index.html:42:        display: grid; place-items: center;
motion/titulo_seccion/index.html:42:        display: grid; place-items: center;
```

Las catorce ocurrencias son declaraciones CSS estaticas dentro del bloque `<style>` (lineas
42 a 64; el `<script>` de cada archivo empieza a partir de la linea 106 en hook, 101 en
cierre, 95 en lower_third y titulo_seccion). Cero ocurrencias de `visibility` en todo
`motion/`. Ninguna tween toca ninguna de las dos propiedades.

### A6. Construccion de la timeline en contexto asincrono

```
$ grep -rnE "async|await|setTimeout|setInterval|requestAnimationFrame|\.then\(|DOMContentLoaded|addEventListener|onload" motion/ --include=*.html
exit=1
```

Cero coincidencias. Los diez scripts construyen la timeline de forma sincrona en el cuerpo
del `<script>` al final del `<body>`.

Chequeo adicional de entradas externas, por la misma razon:

```
$ grep -rnE "innerHTML|eval\(|fetch\(|import\(|https?://" motion/ --include=*.html
exit=1
```

### A7. `data-duration`, `data-width`, `data-height` en cada root

```
$ grep -rnE "data-composition-id|data-width|data-height|data-duration" motion/ --include=*.html
motion/cierre/horizontal/index.html:89:    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080">
motion/cierre/horizontal/index.html:90:      <div id="pieza" class="clip" data-start="0" data-duration="3.5" data-track-index="1">
motion/cierre/horizontal/index.html:117:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/cierre/index.html:89:    <div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920">
motion/cierre/index.html:90:      <div id="pieza" class="clip" data-start="0" data-duration="3.5" data-track-index="1">
motion/cierre/index.html:117:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/dato_destacado/horizontal/index.html:94:    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080">
motion/dato_destacado/horizontal/index.html:95:      <div id="pieza" class="clip" data-start="0" data-duration="3" data-track-index="1">
motion/dato_destacado/horizontal/index.html:123:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/dato_destacado/index.html:94:    <div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920">
motion/dato_destacado/index.html:95:      <div id="pieza" class="clip" data-start="0" data-duration="3" data-track-index="1">
motion/dato_destacado/index.html:123:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/hook/horizontal/index.html:94:    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080">
motion/hook/horizontal/index.html:95:      <div id="pieza" class="clip" data-start="0" data-duration="2.5" data-track-index="1">
motion/hook/horizontal/index.html:122:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/hook/index.html:94:    <div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920">
motion/hook/index.html:95:      <div id="pieza" class="clip" data-start="0" data-duration="2.5" data-track-index="1">
motion/hook/index.html:122:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/lower_third/horizontal/index.html:83:    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080">
motion/lower_third/horizontal/index.html:84:      <div id="pieza" class="clip" data-start="0" data-duration="4.5" data-track-index="1">
motion/lower_third/horizontal/index.html:112:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/lower_third/index.html:83:    <div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920">
motion/lower_third/index.html:84:      <div id="pieza" class="clip" data-start="0" data-duration="4.5" data-track-index="1">
motion/lower_third/index.html:112:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/titulo_seccion/horizontal/index.html:84:    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080">
motion/titulo_seccion/horizontal/index.html:85:      <div id="pieza" class="clip" data-start="0" data-duration="2" data-track-index="1">
motion/titulo_seccion/horizontal/index.html:112:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
motion/titulo_seccion/index.html:84:    <div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920">
motion/titulo_seccion/index.html:85:      <div id="pieza" class="clip" data-start="0" data-duration="2" data-track-index="1">
motion/titulo_seccion/index.html:112:      document.getElementById("pieza").setAttribute("data-duration", String(DUR));
```

Lectura del hallazgo, que es el que motiva el bloque C:

- `data-width` y `data-height` SI estan en el root de los diez archivos, con el valor correcto
  por orientacion (1080x1920 en los primarios, 1920x1080 en los gemelos), y son estaticos.
- `data-duration` NO esta en ningun root. Vive en el hijo `#pieza` (el `.clip`) con la
  duracion natural de la pieza, y el script lo reescribe desde `duracion_ms` antes de que el
  renderer lo lea. Esto es DELIBERADO y esta escrito en D51 punto 4 ("El root NO declara
  `data-duration`: cuando falta, el renderer infiere la duracion del timeline GSAP").

La traza del propio CLI confirma el mecanismo en tiempo de render:

```
[INFO] Compiled composition metadata {"entryFile":"index.html","staticDuration":0,"width":1080,"height":1920,...}
[INFO] Launching browser for composition probe... {"reasons":["root duration unknown","1 unresolved composition(s)"]}
[INFO] Probed composition duration from browser {"discoveredDuration":2.5,"staticDuration":0}
```

`staticDuration: 0` mas `root duration unknown` mas `discoveredDuration` sondeada del
navegador DESPUES de que el script corrio: la duracion no es estatica, se descubre.

### Tabla resumen del bloque A

| plantilla (y su gemelo) | regla | veredicto | archivo:linea | fragmento exacto |
|---|---|---|---|---|
| las 10 | A1 Math.random / Date.now / performance.now / new Date( / crypto.getRandomValues | OK | ninguno (`grep` exit=1) | sin coincidencias en los `index.html` |
| las 10 | A1 (superficie del runtime vendorizado) | OK con nota | `motion/hook/gsap.min.js:10` (y sus 4 copias identicas) | `function gb(t){return t.sort(function(){return.5-Math.random()})}` |
| las 10 | A2 `repeat: -1` | OK | ninguno (`grep` exit=1) | `repeat: reps` con `if (reps >= 1)` como guarda |
| cierre + horizontal | A3 una timeline, pausada | OK | `motion/cierre/index.html:126`, `motion/cierre/horizontal/index.html:126` | `var tl = gsap.timeline({ paused: true });` |
| dato_destacado + horizontal | A3 | OK | `motion/dato_destacado/index.html:132`, `.../horizontal/index.html:132` | `var tl = gsap.timeline({ paused: true });` |
| hook + horizontal | A3 | OK | `motion/hook/index.html:132`, `.../horizontal/index.html:132` | `var tl = gsap.timeline({ paused: true });` |
| lower_third + horizontal | A3 | OK | `motion/lower_third/index.html:121`, `.../horizontal/index.html:121` | `var tl = gsap.timeline({ paused: true });` |
| titulo_seccion + horizontal | A3 | OK | `motion/titulo_seccion/index.html:121`, `.../horizontal/index.html:121` | `var tl = gsap.timeline({ paused: true });` |
| las 10 | A4 `gsap.set` al cargar | OK | ninguno (`grep` exit=1) | solo se usa `gsap.timeline`; ademas es escena unica |
| las 10 | A5 tweens sobre display / visibility | OK | ninguno en `<script>` | las 14 ocurrencias de `display` son CSS estatico (lineas 42-64); cero `visibility` |
| las 10 | A6 timeline en async / await / setTimeout / rAF / .then( | OK | ninguno (`grep` exit=1) | construccion sincrona al final del `<body>` |
| cierre | A7 data-width / data-height en root | OK | `motion/cierre/index.html:89` | `data-width="1080" data-height="1920"` |
| cierre horizontal | A7 | OK | `motion/cierre/horizontal/index.html:89` | `data-width="1920" data-height="1080"` |
| dato_destacado | A7 | OK | `motion/dato_destacado/index.html:94` | `data-width="1080" data-height="1920"` |
| dato_destacado horizontal | A7 | OK | `motion/dato_destacado/horizontal/index.html:94` | `data-width="1920" data-height="1080"` |
| hook | A7 | OK | `motion/hook/index.html:94` | `data-width="1080" data-height="1920"` |
| hook horizontal | A7 | OK | `motion/hook/horizontal/index.html:94` | `data-width="1920" data-height="1080"` |
| lower_third | A7 | OK | `motion/lower_third/index.html:83` | `data-width="1080" data-height="1920"` |
| lower_third horizontal | A7 | OK | `motion/lower_third/horizontal/index.html:83` | `data-width="1920" data-height="1080"` |
| titulo_seccion | A7 | OK | `motion/titulo_seccion/index.html:84` | `data-width="1080" data-height="1920"` |
| titulo_seccion horizontal | A7 | OK | `motion/titulo_seccion/horizontal/index.html:84` | `data-width="1920" data-height="1080"` |
| las 10 | A7 data-duration en root | OK por diseno | ausente del root; esta en `#pieza` (p.ej. `motion/hook/index.html:95`) | `data-duration="2.5"` en el clip, reescrito en `:122` con `setAttribute("data-duration", String(DUR))` |

Cero VIOLACION en el bloque A.

---

## BLOQUE B. Determinismo empirico (marcado `hf_real`, a mano, fuera del CI)

Veinte renders: cinco plantillas por dos orientaciones por dos corridas, cada par con
contrato byte identico y el mismo basename de salida.

### B1 a B3. Tabla de sha256

| plantilla | orientacion | sha256 corrida 1 | sha256 corrida 2 | veredicto | bytes r1 | bytes r2 |
|---|---|---|---|---|---|---|
| cierre | vertical | `f976a007191c0ac558ae0977f149c59730e51b8058098b882e41dfc6be2939ea` | `c3ad891fcbbb4ac208bdc9076b67c6613881ed0830fb0d62e0c030935e2f037c` | **DISTINTO** | 24096248 | 24096245 |
| cierre | horizontal | `3d36f731fa54a64e9d5e1650a24e211571ac104fbe0a24e4a0dc1358f6061775` | `6c7a8b4e155a9b8fe8c6f6c87115f56da02ebf1dabff4c80f16ee60f0ecaac3c` | **DISTINTO** | 30997599 | 30997608 |
| dato_destacado | vertical | `e92ec13630dd8ad4ec61627ba99f940504e194fd50eed54a05d5a8335010851a` | `6c59b6c01e8338b1c05be6ca9f59dc7ade18d1c2c389e60e6a794e0ef397b955` | **DISTINTO** | 14592805 | 14592817 |
| dato_destacado | horizontal | `8ed8c01445adcdda08e6f4ba0d612b9bebcb4be20ec268df4a592ca9139095dd` | `39edb450c869891c09dd3eb599d6b1c757d027f8c89e932a26a6d6385e3694c5` | **DISTINTO** | 20927160 | 20927151 |
| hook | vertical | `4760d41268ff48aef514834f02a398b926b05ea1b694d33ad72b7ca6a4e5f803` | `9857537f0e082de389e0432bd85434f4236c4f5539842b65d5841426efa0b386` | **DISTINTO** | 18713183 | 18713265 |
| hook | horizontal | `30a9c725b6874b82afd9eeb52f22dd168e90165a3ea76b381ea8da251ac8d161` | `8639602e835b18dc4bba664857b4c9685e9a7a94a25307894cf4c4cb5d27dd59` | **DISTINTO** | 28087559 | 28087395 |
| lower_third | vertical | `f8961952a9abd8e792959e0d4b6a49ba989669752a3c61067b24e76b83cf4e8a` | `d4bccb93e40980dca76045d023877848d131d122fb073173fbb5d9a81aa50258` | **DISTINTO** | 15788533 | 15788324 |
| lower_third | horizontal | `cf5a6525d2356a0b0473c9a6f2a272c1452675230580f2225ef4de6584cb1b12` | `c40c203a4b5222e99fefdd8f8131326e95f59775d3579a4bcf4b0e888cffe792` | **DISTINTO** | 15330528 | 15330528 |
| titulo_seccion | vertical | `3ae9ff7534fad99feed7233ece8b4516a5aeae1845a5897c80246fb43bcfbaed` | `3ae9ff7534fad99feed7233ece8b4516a5aeae1845a5897c80246fb43bcfbaed` | IGUAL | 10836118 | 10836118 |
| titulo_seccion | horizontal | `7c0c5c64bad744c51f4b375e9b69cb96108b8bd0e7ce8bdb3dce7d78b07aafb0` | `e5d6d34e1c1ee4bbf3e457fa430ccfd6154eb27f4ae7cf30dfcb80fb0b2d5e35` | **DISTINTO** | 13585871 | 13585956 |

**9 de 10 configuraciones DISTINTO. La exigencia de sha igual NO se cumple.**

El unico IGUAL (titulo_seccion vertical) es la pieza mas corta del catalogo (2000 ms, 60
frames) y no es una excepcion estructural: su gemelo horizontal, con el mismo HTML salvo
lienzo, si sale DISTINTO. El caso `lower_third horizontal` es especialmente informativo:
mismo numero de bytes exacto (15330528) y sha distinto, o sea la diferencia es de contenido,
no de longitud.

### Diferencia visible: donde esta y de que tamano es

No se reparo nada. Se localizo la diferencia en `hook vertical`. Salida literal del analisis
diferencial (`diferencia.py hook_vertical`):

```
### CASO hook_vertical
bytes run1=18713183  run2=18713265  delta=82

--- METADATA DEL CONTENEDOR (format.tags) ---
run1: {"major_brand": "qt  ", "minor_version": "512", "compatible_brands": "qt  ", "encoder": "Lavf62.3.100"}
run2: {"major_brand": "qt  ", "minor_version": "512", "compatible_brands": "qt  ", "encoder": "Lavf62.3.100"}
--- METADATA DEL STREAM v:0 (tags) ---
run1: {"handler_name": "VideoHandler", "vendor_id": "FFMP", "encoder": "Lavc62.11.100 prores_ks"}
run2: {"handler_name": "VideoHandler", "vendor_id": "FFMP", "encoder": "Lavc62.11.100 prores_ks"}
--- duracion / nb_frames ---
run1: duration=2.500000 nb_frames=75 pix_fmt=yuva444p12le 1080x1920
run2: duration=2.500000 nb_frames=75 pix_fmt=yuva444p12le 1080x1920

--- PAQUETES: run1 n=75  run2 n=75 ---
frames con tamano de paquete DISTINTO: 3 de 75
  frame  11: run1=263728 run2=263816 delta=88
  frame  41: run1=265835 run2=265826 delta=-9
  frame  43: run1=263549 run2=263552 delta=3

--- FRAME 11 (primer paquete distinto): extraccion y comparacion ---
PSNR: [Parsed_psnr_0] PSNR r:66.027989 g:74.322300 b:82.576860 a:81.323239 average:71.257552 min:71.257552 max:71.257552
SSIM: [Parsed_ssim_0] SSIM R:0.999988 (49.205383) G:0.999991 (50.540385) B:0.999998 (57.306681) All:0.999992 (51.211530)
```

La metadata del contenedor es IDENTICA en las dos corridas (mismo `encoder`, ningun
`creation_time`), asi que la diferencia de sha NO viene del contenedor: viene de los
pixeles. Solo 3 frames de 75 difieren.

Medicion pixel a pixel de esos tres frames (`diff_pixel.py`, salida literal):

```
--- frame 11 ---
resolucion: 1080x1920  pixeles totales: 2073600
pixeles que difieren: 2097 (0.1011%)
delta maximo por canal (R,G,B,A): [65, 21, 8, 12] sobre 255
delta medio en los pixeles que difieren: 1.67
bounding box de la diferencia: x 384-703  y 1072-1119
  como fraccion del alto: y 0.558 - 0.583
histograma de amplitud (delta 0..7): [0, 1696, 354, 4, 1, 1, 0, 1]
--- frame 41 ---
resolucion: 1080x1920  pixeles totales: 2073600
pixeles que difieren: 1902 (0.0917%)
delta maximo por canal (R,G,B,A): [2, 2, 2, 2] sobre 255
delta medio en los pixeles que difieren: 1.02
bounding box de la diferencia: x 280-919  y 1264-1279
  como fraccion del alto: y 0.658 - 0.666
histograma de amplitud (delta 0..7): [0, 1870, 32, 0, 0, 0, 0, 0]
--- frame 43 ---
resolucion: 1080x1920  pixeles totales: 2073600
pixeles que difieren: 737 (0.0355%)
delta maximo por canal (R,G,B,A): [1, 2, 2, 1] sobre 255
delta medio en los pixeles que difieren: 1.03
bounding box de la diferencia: x 568-695  y 1072-1111
  como fraccion del alto: y 0.558 - 0.579
histograma de amplitud (delta 0..7): [0, 715, 22, 0, 0, 0, 0, 0]
```

**Descripcion de la diferencia visible:** no hay ninguna a ojo. La mascara binaria de los
pixeles que difieren (`auditoria/salida/b/hook_vertical/frames/mascara_zoom.png`, mirada
ampliada 4x) traza exactamente el CONTORNO ANTIALIASEADO de las letras del kicker
("TUTORIAL COMFYUI") y el borde inferior redondeado de la placa. Es varianza de
rasterizacion sub pixel: 1696 de 2097 pixeles del frame 11 tienen delta 1 sobre 255, y el
delta medio es 1.67. No hay desplazamiento de layout, ni de fase de animacion, ni de color de
marca: el bounding box en `y 0.558 - 0.583` es la banda del kicker, y en `y 0.658 - 0.666`
es el borde inferior de la placa. PSNR 71 dB y SSIM 0.999992 lo confirman numericamente.

La diferencia es imperceptible pero REAL: rompe la igualdad de sha256, que es la propiedad
que la cache y el resume del Motor B necesitan.

### Causa raiz acotada (medicion adicional, no pedida pero decisiva)

Se probaron dos hipotesis sobre la misma plantilla (`hook` vertical) y el mismo contrato.

Hipotesis 1, rasterizacion por GPU. Comando:

```
... --no-best-effort --no-browser-gpu
```

| corrida | sha256 | bytes |
|---|---|---|
| sinGPU run1 | `57e3f0c47e45c5842f23f56fc514ee2e09209cc8ab93afc358d7aa1e44391afe` | 18767434 |
| sinGPU run2 | `94df1a5f2de397c69fda0fa308361c4ebb49486b405331704026aef8cd93ec71` | 18769655 |

**DISTINTO.** Forzar SwiftShader no arregla nada. La GPU NO es la causa.

Hipotesis 2, captura en paralelo. El CLI resuelve `workerCount: 2` en modo `auto` en esta
maquina de 16 cores (traza: `[INFO] [Render:trace] {"phase":"worker_resolution",...,"workerCount":2}`).
Comando:

```
... --no-best-effort --workers 1
```

| corrida | sha256 | bytes | segundos |
|---|---|---|---|
| hook 1worker run1 | `3bd1da57ee5dcb80ff22da4d0c5b06eb32b854ec9774f44d68abdcb5d82f9eed` | 18719996 | 5.0 |
| hook 1worker run2 | `3bd1da57ee5dcb80ff22da4d0c5b06eb32b854ec9774f44d68abdcb5d82f9eed` | 18719996 | 4.9 |

**IGUAL.** Confirmado en otras dos plantillas:

| corrida | sha256 | bytes |
|---|---|---|
| cierre 1worker run1 | `51586fe8eeacc837df2f469b8beb856bbc457374a7164d95c648e965c43c1a4a` | 24093361 |
| cierre 1worker run2 | `51586fe8eeacc837df2f469b8beb856bbc457374a7164d95c648e965c43c1a4a` | 24093361 |
| lower_third 1worker run1 | `c3184336bdb69715a8e42e811a23fb7ce2f1eb58972ea654ec59644bfa7c60b9` | 15795636 |
| lower_third 1worker run2 | `c3184336bdb69715a8e42e811a23fb7ce2f1eb58972ea654ec59644bfa7c60b9` | 15795636 |

**3 de 3 plantillas byte identicas con `--workers 1`.** La no reproducibilidad viene de la
captura repartida entre dos procesos de Chrome, no de las plantillas, ni del contrato, ni de
la GPU, ni del contenedor. Se reporta y no se repara, segun la regla de la tarea.

---

## BLOQUE C. Gobierna `duracion_ms` de verdad?

Sospecha a comprobar: que `data-duration` fuese autoridad estatica igual que
`data-width` y `data-height`, y que `duracion_ms` se estuviera ignorando en silencio.

Cuatro renders, todos verticales, cambiando SOLO `duracion_ms` respecto del ejemplo.
Medicion con `ffprobe` (`format=duration` mas conteo real de paquetes de video).

| plantilla | `duracion_ms` pedida | returncode | duracion REAL medida (ms) | desvio | paquetes de video | fps | pix_fmt |
|---|---|---|---|---|---|---|---|
| hook (C1) | 2500 | 0 | **2500** | +0 ms | 75 | 30/1 | yuva444p12le |
| hook (C2) | 4000 | 0 | **4000** | +0 ms | 120 | 30/1 | yuva444p12le |
| cierre (C5) | 3500 | 0 | **3500** | +0 ms | 105 | 30/1 | yuva444p12le |
| cierre (C5) | 5000 | 0 | **5000** | +0 ms | 150 | 30/1 | yuva444p12le |

Salida literal del arnes:

```
  hook pedida=2500 rc=0 real=2500
  hook pedida=4000 rc=0 real=4000
  cierre pedida=3500 rc=0 real=3500
  cierre pedida=5000 rc=0 real=5000
```

Detalle de `ffprobe` por caso:

```
hook     pedida= 2500 rc=0 real= 2500 desvio=+0 ms  paquetes=75  fps=30/1 1080x1920 yuva444p12le format.duration=2.500000
hook     pedida= 4000 rc=0 real= 4000 desvio=+0 ms  paquetes=120 fps=30/1 1080x1920 yuva444p12le format.duration=4.000000
cierre   pedida= 3500 rc=0 real= 3500 desvio=+0 ms  paquetes=105 fps=30/1 1080x1920 yuva444p12le format.duration=3.500000
cierre   pedida= 5000 rc=0 real= 5000 desvio=+0 ms  paquetes=150 fps=30/1 1080x1920 yuva444p12le format.duration=5.000000
```

Y los sha256 de los cuatro, todos distintos entre si (la duracion cambia la salida):

```
  hook_2500:   a0ec01bc611fcd8a7d3ba5a3733e007e22730706413ae5293ecf10a1b35d2f46
  hook_4000:   dcf5d2c0da82106a0761cb5823f301e3139ba99c009cc94a02e89d9457dcb8f4
  cierre_3500: 103946c6480934bd45589c0ea1d600de83dad689cf3a5272a7f06c18cced92d7
  cierre_5000: 8b71663a97477914c0874e38a9c0312c4389d44b07882bf5f3a608c681e9f9fa
```

### C4 y C5. Veredicto explicito

**`duracion_ms` GOBIERNA.**

Desvio de 0 ms en las cuatro mediciones, con el conteo de paquetes cuadrando exactamente
(`duracion_ms / 1000 * fps`: 2500 da 75, 4000 da 120, 3500 da 105, 5000 da 150). Se verifico
en dos plantillas de duracion natural distinta (hook 2500, cierre 3500) y en ambas
direcciones respecto de su `data-duration` estatico. No hay redondeo al valor estatico ni
truncado silencioso.

La sospecha queda REFUTADA con evidencia, y el mecanismo esta identificado en A7: a
diferencia de `data-width` y `data-height`, que si son autoridad estatica del root,
`data-duration` no esta en el root. El renderer registra `staticDuration: 0` y
`root duration unknown`, lanza una sonda de navegador y descubre la duracion del timeline
GSAP ya construido con `duracion_ms`. Los `data-duration` del `#pieza` son valores por
defecto que el script reescribe antes de la sonda.

---

## BLOQUE D. Campo `sha` del CLI

### D1. Render con `--json`

Primer intento, `--json` sobre el comando de produccion tal cual:

```
C:\Program Files\nodejs\npx.CMD hyperframes render C:\CLAUDECODE\ediciondevideo\motion\hook --format mov --quality high --fps 30 --output ...\pieza.mov --variables-file ...\pieza-variables.json --no-best-effort --json
```

`returncode = 0`, MOV producido (18713528 bytes), y **stdout sin ningun documento JSON**. Lo
que sale por stdout es la interfaz de progreso del CLI:

```
◆  Rendering hook → C:\CLAUDECODE\hyperframes-lab\auditoria\salida\d\json\pieza.mov
   30fps · high · auto workers (16 cores detected)
   GPU: browser GPU (auto-detect)
...
  █████████████████████████  100%  Render complete

◇  C:\CLAUDECODE\hyperframes-lab\auditoria\salida\d\json\pieza.mov
   17.8 MB · 2.5s video · rendered in 9.8s
```

Busqueda literal de la cadena `sha` en stdout mas stderr completos de ese render:

```
--- ocurrencias de "sha" (case-insensitive) en stdout+stderr ---
total ocurrencias: 1
'se,"usePageSideCompositing":false,"hasHdrContent":false,"hasShaderTransitions":false,"isPngSequence":false}'
```

La unica coincidencia es `hasShaderTransitions`, un falso positivo. **Cero campos `sha`.**

Esto es coherente con la ayuda del propio CLI, que acota el flag:

```
--json    With --batch, emit exactly one final JSON result document. (Default: false)
```

Segundo intento, en el modo documentado. `--batch` resulto ser mutuamente excluyente con
`--variables-file`:

```
✗  Conflicting variables flags

   Use either --batch or --variables/--variables-file, not both.
```

Tercer intento, con las variables dentro del lote. Comando:

```
npx hyperframes render C:\CLAUDECODE\ediciondevideo\motion\hook --format mov --quality high --fps 30 --output ...\batch2\pieza.mov --no-best-effort --batch ...\batch2\lote.json --json
```

Salida JSON completa, literal (el unico documento que el CLI emite):

```json
{"type":"batch-complete","manifestPath":"C:\\CLAUDECODE\\hyperframes-lab\\auditoria\\salida\\d\\batch2\\manifest.json","total":1,"completed":1,"failed":0,"skipped":0,"rows":[{"index":0,"outputPath":"C:\\CLAUDECODE\\hyperframes-lab\\auditoria\\salida\\d\\batch2\\pieza.mov","status":"completed","durationMs":2500,"renderTimeMs":9560,"error":null,"startedAt":"2026-08-04T15:19:18.226Z","completedAt":"2026-08-04T15:19:27.900Z","variables":{"kicker":"Tutorial ComfyUI","titulo":"Entrena tu LoRA de personaje en 20 minutos","marca_primario":"#FF5A2B","marca_secundario":"#111111","marca_texto":"#FFFFFF","duracion_ms":2500,"fps":30,"tamano_ancho":1080,"tamano_alto":1920,"semilla":0}}]}
```

Y el `manifest.json` que ese modo escribe en disco, completo:

```json
{
  "version": 1,
  "batchPath": "C:\\CLAUDECODE\\hyperframes-lab\\auditoria\\salida\\d\\batch2\\lote.json",
  "manifestPath": "C:\\CLAUDECODE\\hyperframes-lab\\auditoria\\salida\\d\\batch2\\manifest.json",
  "total": 1,
  "completed": 1,
  "failed": 0,
  "skipped": 0,
  "rows": [
    {
      "index": 0,
      "outputPath": "C:\\CLAUDECODE\\hyperframes-lab\\auditoria\\salida\\d\\batch2\\pieza.mov",
      "status": "completed",
      "durationMs": 2500,
      "renderTimeMs": 9560,
      "error": null,
      "startedAt": "2026-08-04T15:19:18.226Z",
      "completedAt": "2026-08-04T15:19:27.900Z",
      "variables": {
        "kicker": "Tutorial ComfyUI",
        "titulo": "Entrena tu LoRA de personaje en 20 minutos",
        "marca_primario": "#FF5A2B",
        "marca_secundario": "#111111",
        "marca_texto": "#FFFFFF",
        "duracion_ms": 2500,
        "fps": 30,
        "tamano_ancho": 1080,
        "tamano_alto": 1920,
        "semilla": 0
      }
    }
  ]
}
```

Busqueda de `sha` en ambos:

```
$ grep -oiE ".{0,40}sha.{0,60}" manifest.json stdout.txt
SIN OCURRENCIAS de 'sha'
```

### D2. Comparacion contra nuestro sha256

No hay campo que comparar. El sha256 que calculamos del MOV de ese batch es
`8a17a24d59575fb7a8bf5dadcc7d3b327e2e671320e1552063cd3563bae5e11f`, y no aparece ni en el
JSON ni en el manifiesto.

El unico hash que el CLI si emite es `compositionHash`, y sale por STDERR dentro de las
trazas, no por el JSON:

```
[INFO] [Render:trace] {"phase":"compile","status":"checkpoint","message":"composition metadata resolved","width":1080,"height":1920,...,"compositionHash":"0dceb4f34338fb49"}
```

Se caracterizo con tres renders de la misma plantilla cambiando una cosa cada vez:

| caso | `compositionHash` | sha256 del MOV |
|---|---|---|
| A, ejemplo tal cual (2500 ms) | `0dceb4f34338fb49` | `3f5088fcd3d2c5919ef8852677c9d89f854fb9f6381e3b190a4379e8c8b86da7` |
| B, mismo todo con `titulo` distinto | `9f978ce54fa59676` | `3bed3fa5966992dddf216326158ed1c10ebb61190cfc991b5b6e7f71609d5034` |
| C, mismo todo con `duracion_ms` 4000 | `d7e87708a4d80200` | `968e079d6e887382f263f8174b0b76a85ef67dbd6bb1c1b9a0928447c39dca02` |
| D1 (render aparte, contrato IDENTICO al caso A) | `0dceb4f34338fb49` | `8a55089b6b4b688dd2afc6ade2bc4bff852a61c4d52a96b077fe4c7bf2f99ee8` |

### D3. Veredicto

**No existe un campo `sha` en la salida del CLI, ni en `--json`, ni en `--batch --json`, ni
en el `manifest.json`.** Lo que la ruta de HF-1 llama `sha` es propio del repo, no del CLI:

- `Resultado.sha256` (`hyperframes/servicio.py:49`) se llena en `hyperframes/servicio.py:208`
  con `almacen.sha256_de(mov)`, es decir el repo abre el MOV y lo hashea el mismo
  (`hyperframes/almacen.py:68-70`). Es **el hash del archivo de salida**, calculado
  localmente.
- `Resultado.hash` (`hyperframes/servicio.py:43`) es la clave de cache que calcula
  `hyperframes/contrato.py:219-234`: `sha256` del contrato canonico mas nombre y version de
  plantilla mas las cuatro versiones del entorno. Es **una huella de las entradas**, y no
  toca el archivo producido.

Sobre `compositionHash`, que es lo mas parecido a un "campo sha del CLI": es **una huella de
las entradas resueltas**, no del archivo de salida. La evidencia es la comparacion de las
filas A y D1 de la tabla: mismo contrato, mismo `compositionHash` `0dceb4f34338fb49`, y sin
embargo dos MOV con sha256 distinto (`3f5088fc...` frente a `8a55089b...`). Un hash del
archivo de salida no podria coincidir cuando los archivos difieren. Que ademas cambie con el
texto (fila B) y con la duracion (fila C) confirma que cubre variables, no solo el HTML
fuente. Justificado con medicion, sin apoyarse en la documentacion.

### D4

No se cambio nada del codigo de HF-1. Solo se reporta.

---

## VEREDICTO

### BLOQUEANTES DE HF-3

1. **`hyperframes/invocador.py:134-150` (`construir_comando`) no fija `--workers`, y el MOV no
   es reproducible.** El comando deja el reparto de captura en `auto`, que en esta maquina
   resuelve `workerCount: 2`, y 9 de las 10 configuraciones medidas dieron sha256 distinto
   entre dos corridas con contrato byte identico (bloque B). Bloquea porque HF-3 tiene que
   meter las piezas del Motor B dentro del paquete y hacerlas sobrevivir a un resume
   (`auto.py:179` `_paquete_dir` y `auto.py:278` `_paquete_dir_v2`): con la salida variando
   por corrida, un resume que re-renderice una pieza produce un archivo distinto del que ya
   se compuso, y la propiedad "los clips no reprocesados quedan byte identicos" que el
   proyecto verifica desde S36-C2C deja de valer para el Motor B. La causa esta acotada y
   medida: con `--workers 1`, 3 de 3 plantillas salieron byte identicas.

2. **`tests/test_hf2_real.py:81` (`assert uno.sha256 != otro.sha256`) quedo INERTE.** Es el
   canario de influencia de D50.5, la unica compuerta automatica que detecta el fallo de
   D50.1 (un slot que no llega a la plantilla, que pinta su default y devuelve returncode 0
   sin que nada lo vea). Como dos renders del MISMO contrato ya difieren en sha256 (bloque
   B), la asercion se satisface por ruido y no puede fallar por la razon para la que se
   escribio. Bloquea porque HF-3 va a ejercitar el aplanado de variables desde Auto y desde
   el Studio, que es exactamente la superficie que ese canario protege.

### DEUDAS NO BLOQUEANTES

1. **`semilla` esta declarada en las diez plantillas y no la consume ninguna.**
   `motion/hook/index.html:12` (y las nueve gemelas: `motion/cierre/index.html:12`,
   `motion/dato_destacado/index.html:12`, `motion/lower_third/index.html:12`,
   `motion/titulo_seccion/index.html:11` y sus cuatro horizontales). El grep de lecturas
   `v.<algo>` en los diez scripts no devuelve `v.semilla` ni una vez. Como si entra al
   aplanado (`hyperframes/invocador.py:86`) y por tanto al hash de cache
   (`hyperframes/contrato.py:227`), cambiarla invalida la cache sin cambiar un solo pixel, y
   no sirve para lo que su nombre promete (fijar una fuente de azar que no existe).

2. **Los defaults de lienzo del gemelo horizontal apuntan a vertical.**
   `motion/hook/horizontal/index.html:10-11` declara `tamano_ancho` 1080 y `tamano_alto` 1920
   contra un root que es `data-width="1920" data-height="1080"` (`:94`). Mismo desajuste en
   los otros cuatro gemelos. No es alcanzable por el invocador, que siempre manda las
   variables, pero un render manual sin variables maqueta el DOM a 1080x1920 sobre un lienzo
   1920x1080.

3. **El runtime GSAP vendorizado trae `Math.random` y `Date.now`.**
   `motion/hook/gsap.min.js:10` y sus cuatro copias identicas (3 y 2 ocurrencias
   respectivamente por archivo). Ninguna plantilla llama a las utilidades que los alcanzan y
   el timeline se recorre por seek, no por ticker, pero la superficie existe y ningun test la
   vigila.

4. **`--json` sin `--batch` no emite nada y no lo avisa.** El render devuelve returncode 0,
   escribe el MOV y deja stdout sin documento JSON. Cualquier integracion futura que asuma
   JSON en stdout va a recibir vacio en silencio, que es el mismo patron de fallo mudo que
   D50.1.

### VERIFICADO LIMPIO

1. **A1:** cero `Math.random`, `Date.now`, `performance.now`, `new Date(` y
   `crypto.getRandomValues` en los diez `index.html` (grep exit=1).
2. **A2:** cero `repeat: -1` en cualquier variante de espacios o comillas (grep exit=1); las
   diez repeticiones son finitas y estan guardadas por `if (reps >= 1)`.
3. **A3:** exactamente una timeline por archivo, las diez con `paused: true` explicito, cero
   `paused: false`, y una unica entrada `__timelines["main"]` por archivo.
4. **A4:** cero `gsap.set` (grep exit=1); las plantillas solo usan `gsap.timeline`, y ademas
   son de escena unica, asi que no existen escenas posteriores que adelantar.
5. **A5:** cero tweens sobre `display` o `visibility`; las catorce ocurrencias de `display`
   son CSS estatico en el bloque `<style>`, y `visibility` no aparece en todo `motion/`.
6. **A6:** cero `async`, `await`, `setTimeout`, `setInterval`, `requestAnimationFrame`,
   `.then(`, `DOMContentLoaded`, `addEventListener` y `onload` (grep exit=1); la timeline se
   construye de forma sincrona al final del `<body>`.
7. **A7:** `data-width` y `data-height` presentes y correctos en los diez roots (1080x1920 en
   los primarios, 1920x1080 en los gemelos). La ausencia de `data-duration` en el root es
   deliberada (D51 punto 4) y esta verificada en funcionamiento por el bloque C.
8. **Bloque C: `duracion_ms` GOBIERNA.** Desvio de 0 ms en 4 de 4 mediciones, en dos
   plantillas de duracion natural distinta y en ambas direcciones respecto del
   `data-duration` estatico, con el conteo de paquetes cuadrando exactamente. La sospecha de
   que se estuviera ignorando en silencio queda refutada.
9. **Higiene de entradas externas:** cero `innerHTML`, `eval(`, `fetch(`, `import(` y
   `http(s)://` en los diez `index.html` (grep exit=1). El render reproduce sin red.
10. **La diferencia del bloque B no es de diseno.** Metadata de contenedor identica, sin
    `creation_time`; mismo `nb_frames`, misma duracion, mismo `pix_fmt yuva444p12le`, mismo
    lienzo. Solo 3 frames de 75 difieren, con delta medio de 1.67 sobre 255 sobre el contorno
    antialiaseado del texto. Ni el layout, ni la fase de animacion, ni los colores de marca se
    mueven entre corridas.
11. **La causa del bloque B esta acotada por medicion, no por hipotesis.** No es la GPU
    (`--no-browser-gpu` sigue dando DISTINTO), no es el contenedor, no son las plantillas: es
    la captura repartida entre dos procesos de Chrome. Con `--workers 1`, hook, cierre y
    lower_third dieron sha256 byte identico en 3 de 3.

### Puntos BLOQUEADOS

Ninguno. Los cuatro bloques se ejecutaron completos con evidencia pegada.

---

## Ubicacion de la evidencia

Los renders de medicion viven fuera del repo, en
`C:\CLAUDECODE\hyperframes-lab\auditoria\`:

| ruta | contenido |
|---|---|
| `medir.py`, `diferencia.py`, `diff_pixel.py` | el arnes de medicion |
| `salida/b/resultado.json` | los 20 renders del bloque B con comando, sha256 y bytes |
| `salida/b/hook_vertical/frames/` | frames 11, 41 y 43 de ambas corridas, mascara de diferencia y zooms 4x |
| `salida/c/resultado.json` | los 4 renders del bloque C con el `ffprobe` completo |
| `salida/d/resultado.json`, `salida/d/batch2/` | bloque D: `--json`, `--batch --json`, manifiesto |
| `salida/e/resultado.json`, `salida/f/resultado.json` | hipotesis de causa raiz (GPU y workers) |
