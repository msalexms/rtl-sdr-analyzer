# AMSTech UI · v1.0

Letras, colores y componentes de la marca AMSTech para cualquier proyecto. Sigue el **manual de marca v1.5** (dirección «Solo pegatinas», sin orejas en las cajas, modo noche suave).

Sin dependencias ni compilación: tres hojas CSS, un JS opcional, las letras y los logos. Abre `ejemplo.html` para ver todos los componentes en claro y en noche.

```
amstech-ui/
├─ fuentes.css          @font-face de las tres letras (apuntan a fuentes/)
├─ tokens.css           todas las variables --ams-… (claro, noche y auto)
├─ componentes.css      componentes con prefijo ams-
├─ amstech-ui.js        opcional: logo en línea, barra de capítulos, deslizadores, copiar, tema
├─ fuentes/             Bricolage Grotesque (variable), Figtree 400–800, DM Mono 400–500 · latín + latín ext. · licencias OFL
├─ logo/                thor.svg, thor-plano.svg, thor-blanco.svg, thor-noche.svg, favicon.svg, avatar.svg, marca-completa.svg,
│                        sello.svg, sello-noche.svg, sello-en.svg
└─ ejemplo.html         todos los componentes, con selector de tema
```

## Instalar en un proyecto

1. Copia la carpeta `amstech-ui/` dentro de lo que sirve tu app (por ejemplo `public/amstech-ui/`).
2. En el `<head>`:

   ```html
   <link rel="stylesheet" href="amstech-ui/fuentes.css">
   <link rel="stylesheet" href="amstech-ui/tokens.css">
   <link rel="stylesheet" href="amstech-ui/componentes.css">
   <link rel="icon" href="amstech-ui/logo/favicon.svg" type="image/svg+xml">
   <script src="amstech-ui/amstech-ui.js" defer></script>  <!-- opcional -->
   ```

3. Pon `class="ams"` en `<body>` (o en el contenedor de la app) para heredar fondo, letra y color.

Todo funciona **sin internet**: las letras van dentro y no se pide nada fuera. Es compatible con una `Content-Security-Policy` que solo permita `'self'` (scripts, estilos y fuentes).

Para actualizar un proyecto, sustituye la carpeta entera. Lo propio de cada app va en su CSS, nunca dentro de `amstech-ui/`.

## Tema: claro, noche y automático

```html
<html data-tema="claro">   <!-- o "noche"; sin atributo (o "auto") sigue al sistema -->
```

```js
amsUI.tema('noche', { recordar: true });   // 'claro' | 'noche' | 'auto'; recordar = lo guarda en localStorage («ams-tema»)
```

Para evitar el parpadeo al abrir, aplica el tema guardado antes de pintar (en el `<head>`):

```html
<script>try { const t = localStorage.getItem('ams-tema'); if (t && t !== 'auto') document.documentElement.dataset.tema = t; } catch {}</script>
```

Si una app ya guarda el tema en otro sitio (ams_lab lo guarda en el servidor), basta con poner `data-tema` en `<html>`: los tokens hacen el resto.

## Variables principales

| Variable | Para qué | Claro | Noche |
|---|---|---|---|
| `--ams-fondo` | fondo de la página | `#FFF6E9` | `#18181D` |
| `--ams-superficie` | cajas, campos | `#FFFFFF` | `#222229` |
| `--ams-borde` | bordes de 2,5 px | `#1E1B2E` | `#3A3A45` |
| `--ams-sombra` | sombra dura | `5px 5px 0` tinta | `3px 3px 0 #0E0E12` |
| `--ams-texto` / `--ams-gris` | texto / secundario | `#1E1B2E` / `#5A5670` | `#E9E6E0` / `#9E9AA8` |
| `--ams-marca` | botón principal, enlaces | `#2B36D9` | `#7F89E8` |
| `--ams-principal` | la caja azul | `#2B36D9` | `#262A55` |
| `--ams-amarillo` | destacado | `#FFE27A` (relleno) | `#D9C26A` (solo contornos y rayas) |
| `--ams-serie-*` | colores de serie | iguales en los dos modos | |
| `--ams-tinte` | % al teñir con el color de serie | 38 % | 12 % |

Letras: `--ams-letra-marca`, `--ams-letra`, `--ams-letra-mono`. Forma: `--ams-radio` (6 px), `--ams-borde-ancho` (2,5 px). Espacios: `--ams-e1` … `--ams-e7`.

## Componentes

| Clase | Qué es |
|---|---|
| `ams-portada`, `ams-titulo`, `ams-h2`, `ams-h3`, `ams-rotulo` | titulares (Bricolage) y rótulo en mayúsculas |
| `ams-caja` (+ `--principal`, `--serie`, `--plana`, `--crema`, `--sin-relleno`) | la caja de plastilina; `--serie` usa `style="--ams-c: var(--ams-serie-cripto)"` |
| `ams-fila` | fila con separador dentro de una caja |
| `ams-btn` (+ `--principal`, `--amarillo`, `--peligro`, `--peq`, `--icono`) | botones |
| `ams-etiqueta` (+ `--amarilla`, `--ok`, `--mal`, `--serie`) · `ams-punto` · `ams-cuadro` | etiquetas y marcas de estado |
| `ams-aviso` | el «Ojo» y los avisos con arreglo |
| `ams-cajetin` | caja de datos: `<dl class="ams-cajetin" style="--cols:2"><div><dt>…</dt><dd>…</dd></div></dl>` (`.ancho` ocupa dos columnas) |
| `ams-tabla` | tablas (pines, conexiones, versiones) |
| `ams-campo`, `ams-entrada`, `ams-select`, `ams-area` | formularios |
| `ams-interruptor`, `ams-segmentos`, `ams-rango` | interruptor, botones segmentados y deslizador |
| `ams-cabecera`, `ams-marca`, `ams-pestanas`, `ams-migas` | cabecera de la app |
| `ams-barra-movil` (+ `ams-fab`) | barra de abajo en el móvil |
| `ams-barra-cap` | barra de capítulos (con `amsUI.barraCapitulos`) |
| `ams-terminal` | comandos, con botón «Copiar» |
| `ams-menu`, `dialog.ams-dialogo`, `ams-aviso-flotante` | menús, diálogos y avisos flotantes |
| `ams-pegatina`, `ams-dibujo` | pegatinas (sombra dura) y dibujos/fotos (bajan el brillo en noche) |
| `ams-denso` | en un contenedor: quita la sombra a las cajas anidadas (telemetría, listas largas) |

### JavaScript (opcional)

```js
el.innerHTML = amsUI.thor(36, { etiqueta: 'AMSTech' });          // logo en línea, sigue al tema
el.innerHTML = amsUI.barraCapitulos({ total: 4, actual: 1,
  etiquetas: ['01', '02', '03', '04'], enlaces: ['#1', '#2', '#3', '#4'], nombre: 'Episodios' });
amsUI.rangos();      // pinta la parte llena de los .ams-rango
amsUI.terminales();  // activa los botones «Copiar» de .ams-terminal
```

## Reglas de la marca (resumen del manual)

- **Una caja azul** (`ams-caja--principal`) y **un botón principal** por pantalla.
- **Las orejas solo en el logo y en la barra de capítulos.** Nunca en cajas, botones, fotos ni miniaturas.
- El texto siempre en `--ams-texto` (o blanco sobre la caja azul). Los colores de serie solo en pegatinas y fondos teñidos.
- El amarillo marca lo seleccionado y lo destacado; el rojo señal, solo el punto de la barra y «en directo».
- En noche: nada de rellenos amarillos ni cobalto puro, ni bordes claros o sombras largas.
- Miniaturas, avatar y portada del PDF no cambian con el tema.

## Lemas

| Nivel | Lema | Dónde |
|---|---|---|
| Marca (tú y AMSTech) | **Hecho para mí, compartido con todos** · *Built for me, shared with all* | perfil, web, portfolio, firma |
| Canal y series | **Tecnología, sin humo** | final de los vídeos, miniaturas, PDF |
| Proyectos y apps | **Un proyecto de AMSTech** · *An AMSTech project* + qué se comparte («Código abierto · MIT» / «Explicado en vídeo · código privado») | pie, README, «Sobre»; con el sello |

El sello (`logo/sello-*.svg`) va pequeño (48–120 px) en el pie, en el README o en la contraportada; nunca en la cabecera ni en lugar del logo.

## Por proyecto

**ams_lab** (español, Node + `public/`). Copiar a `public/amstech-ui/` y enlazar en `public/index.html`. Ya usa `data-tema="claro|noche|auto"` en `<html>`, así que los tokens siguen su selector de tema sin cambios. Sus colores de función de pin (`funciones_pin`) siguen siendo suyos. Habría que decidir qué hacer con «Ajustes → Letra»: dejar «AMSTech» por defecto o quitar la opción. El service worker (`sw.js`) debe incluir los archivos nuevos en su caché para que funcione sin conexión.

**iphone-camera** (inglés, Vite). Copiar a `public/amstech-ui/` o importar los CSS desde `src/shared.css`. Sustituye a `@fontsource/jetbrains-mono`. La CSP actual (`'self'`) ya permite estas letras. Los textos de los componentes no dependen del idioma. Después de cambiar la interfaz, `npm run test:ui`.

## Versiones

- **1.0** (noviembre 2026): primera versión, a partir del manual de marca v1.3.

Letras: Bricolage Grotesque, Figtree y DM Mono, bajo SIL Open Font License 1.1 (ver `fuentes/LICENCIA-*.txt`), tomadas de Fontsource 5.3.0.
