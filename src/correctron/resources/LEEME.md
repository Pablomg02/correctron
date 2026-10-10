# Formato de datos de Correctron

Esta carpeta es la **única fuente de verdad** de Correctron. Todo son archivos
normales (CSV, JSON, Markdown y PDF) que puedes abrir y editar sin la
herramienta: con un editor de texto, con una hoja de cálculo o con un LLM. La
web de Correctron lee los archivos en cada petición, así que verá enseguida
cualquier cambio que hagas a mano, y nunca sobrescribe en silencio un archivo
que haya cambiado fuera de ella.

Este documento describe cada archivo y cada columna. Correctron lo escribe en
la raíz de la carpeta de datos si no existe; si lo editas, no lo vuelve a
sobrescribir.

## Estructura

```
<carpeta de datos>/
├── LEEME.md                         este documento
├── .papelera/<AAAAMMDD-HHMMSS>/…    archivos subidos que se borraron (oculta)
└── <asignatura>/                    cualquier carpeta no oculta = una asignatura
    ├── asignatura.json              opcional
    ├── alumnos.csv                  alumnos de la asignatura
    └── <examen>/                    una subcarpeta con config.json = un examen o trabajo
        ├── config.json
        ├── alumnos.csv              alumnos del examen (con «presentado»)
        ├── enunciado/               cualquier archivo (enunciado, rúbrica, soluciones…)
        ├── entregas/<id>/original/  la entrega original del alumno (cualquier archivo)
        ├── entregas/<id>/corregido/ la versión corregida (cualquier archivo)
        ├── notas/<corrector>.csv    una hoja de notas por corrector
        ├── notas/<corrector>/<id>.md  comentario largo opcional
        ├── notas/final.csv          notas oficiales
        ├── notas/final/<id>.md      comentario largo oficial opcional
        └── revisiones/NN-AAAA-MM-DD.csv
```

Reglas generales:

- **Oculto** significa que el nombre empieza por `.` o `_`. Las carpetas y
  archivos ocultos se ignoran.
- Una **asignatura** es cualquier carpeta no oculta que esté directamente en la
  raíz de datos. Un **examen** (o trabajo) es cualquier subcarpeta de una
  asignatura que contenga `config.json`. Las demás subcarpetas se ignoran, así
  que puedes guardar tus propias carpetas.
- Las carpetas que crea la web se llaman `slugify(nombre)`: minúsculas, sin
  tildes, y cualquier carácter que no sea letra o número se convierte en `-`.
  Si el nombre ya existe se añade `-2`, `-3`…
- Al borrar un archivo subido desde la web, se mueve a
  `.papelera/<AAAAMMDD-HHMMSS>/<ruta relativa>`; no se pierde.
- Quitar un alumno de una lista solo borra su fila: sus notas, comentarios y
  entregas se conservan y aparecen como avisos «fuera de la lista».

### Reglas comunes de los CSV

- UTF-8, una fila de cabecera, separador **coma** y decimales con **punto**
  (`7.5`).
- Correctron también lee archivos con `;` o tabulador como separador, con BOM,
  en cp1252 (Excel) y con decimales con coma (`7,5`). Al reescribir un archivo
  conserva su separador, su codificación y su BOM.
- Un valor copiado de un archivo a otro se escribe en forma canónica: un número
  válido se escribe con punto y sin ceros sobrantes (`7,50` → `7.5`,
  `8.00` → `8`); un valor no válido se copia tal cual.
- Los nombres de columna no distinguen mayúsculas y se escriben en minúsculas.
- Las columnas que no se describen aquí se conservan tal cual.
- Las filas en blanco se ignoran.
- `id` es la clave en todos los CSV.
- Cuando la web reescribe un CSV, ordena las filas por `id`.
- Un valor que Correctron no entiende se muestra en rojo y se conserva sin
  cambios. Una fila con más celdas que la cabecera bloquea la escritura desde
  la web hasta que la corrijas a mano.

## asignatura.json

Datos de la asignatura. Todas las claves son opcionales y las claves
desconocidas se conservan.

| Clave | Significado |
| --- | --- |
| `nombre` | Nombre de la asignatura. Por defecto, el nombre de la carpeta. |
| `curso` | Curso académico, por ejemplo `2026-2027`. |
| `codigo` | Código de la asignatura (opcional). |

Ejemplo:

```json
{ "nombre": "Mecánica de Vuelo", "curso": "2026-2027", "codigo": "" }
```

## alumnos.csv (asignatura)

Lista de alumnos de la asignatura.

Columnas: `id,apellidos,nombre,email,observaciones`. Obligatorias: `id`,
`apellidos` y `nombre`.

- `id`: identificador del alumno, con la forma `apellidos-nombre` en
  minúsculas, sin tildes y con `-` en lugar de espacios u otros caracteres
  (patrón `[a-z0-9]+(-[a-z0-9]+)*`). Se genera una vez al crear el alumno y no
  cambia aunque se edite el nombre. Los homónimos reciben `-2`, `-3`… Un `id`
  que no siga el patrón es un *aviso*, no un error: puedes escribir otros ids a
  mano.
- `apellidos`, `nombre`: nombre del alumno. Si los cambias desde la web, se
  actualizan también en los `alumnos.csv` de todos los exámenes de la
  asignatura.
- `email`: correo (opcional).
- `observaciones`: texto libre (opcional).

Ejemplo:

```csv
id,apellidos,nombre,email,observaciones
alvarez-lopez-ana,Álvarez López,Ana,ana@example.org,
fernandez-rey-carlos,Fernández Rey,Carlos,carlos@example.org,
otero-vidal-sara,Otero Vidal,Sara,sara@example.org,Repetidora
```

## config.json

Configuración de un examen o trabajo. Su presencia es lo que convierte una
carpeta en un examen.

| Clave | Valores | Por defecto |
| --- | --- | --- |
| `nombre` | texto | el nombre de la carpeta |
| `tipo` | `examen` o `trabajo` | `examen` |
| `fecha` | `AAAA-MM-DD` o `""` | `""` |
| `nota_maxima` | número > 0 | `10` |
| `decimales` | entero entre 0 y 4 (decimales de la nota total) | `2` |
| `calculo_total` | `suma`, `ponderada` o `manual` | `suma` |
| `criterios` | lista de criterios | `[]` |

Criterios (como mucho dos niveles):

- Cada criterio de primer nivel tiene `id` y `nombre` (por defecto, el `id`) y
  además **o bien** `maximo` (número > 0; es una *hoja*) **o bien**
  `subcriterios` (una lista no vacía de hojas `{id, nombre, maximo}`; es un
  *grupo*). Nunca ambos y nunca ninguno.
- `peso` (número ≥ 0, por defecto `1`) solo se permite en los criterios de
  primer nivel y solo se usa en el modo `ponderada`.
- Todos los `id` (de cualquier nivel) siguen el patrón `^[a-z0-9][a-z0-9_]*$`,
  son únicos y no pueden ser una columna reservada: `id`, `alumno`, `total`,
  `comentario`, `origen`, `motivo` ni `version`.
- Solo las **hojas** son columnas en los CSV de notas. El subtotal de un grupo
  se calcula, nunca se guarda.
- Las claves desconocidas de primer nivel se conservan. Las claves
  desconocidas dentro de un criterio son un *aviso* y se eliminan al guardar.
- *Aviso*: en `suma`, con `criterios` no vacío, la suma de los `maximo` de las
  hojas es distinta de `nota_maxima`.
- *Error*: en `ponderada`, la suma de los `peso` es 0.

Ejemplo:

```json
{
  "nombre": "Primer parcial",
  "tipo": "examen",
  "fecha": "2026-11-03",
  "nota_maxima": 10,
  "decimales": 2,
  "calculo_total": "suma",
  "criterios": [
    { "id": "ej1", "nombre": "Ejercicio 1", "peso": 1, "subcriterios": [
        { "id": "ej1a", "nombre": "Apartado a", "maximo": 2 },
        { "id": "ej1b", "nombre": "Apartado b", "maximo": 2 } ] },
    { "id": "ej2", "nombre": "Ejercicio 2", "maximo": 3, "peso": 1 },
    { "id": "ej3", "nombre": "Ejercicio 3", "maximo": 3, "peso": 1 }
  ]
}
```

### Cálculo de la nota total

Las hojas son las columnas del CSV, en el orden de `config.json`. Cada valor
de una hoja debe estar entre `0` y su `maximo`.

- `suma`: total = suma de las hojas, sin escalar.
- `ponderada`: para cada criterio de primer nivel `i`, `frac_i = valor/maximo`
  si es una hoja, o `Σ hojas del grupo / Σ maximo del grupo` si es un grupo;
  total = `nota_maxima · Σ(peso_i · frac_i) / Σ peso_i`.
- `manual` (o sin criterios): total = la celda `total`, entre `0` y
  `nota_maxima`. Las hojas son informativas.
- La nota está **completa** cuando todas las hojas tienen un valor válido
  (modos calculados) o cuando `total` es válido (modo manual). Si está
  incompleta, no hay total. En `suma`, el *parcial* es la suma de las hojas
  rellenas válidas.
- Subtotal de un grupo = suma de sus hojas (ninguno si alguna está en blanco).
  Se muestra, nunca se guarda.
- Redondeo: a `decimales` cifras, redondeando la mitad hacia arriba
  (`6.125` → `6.13`). Se escribe sin ceros sobrantes.

## alumnos.csv (examen)

Lista de alumnos del examen.

Columnas: `id,apellidos,nombre,presentado,observaciones`.

- `id`, `apellidos`, `nombre`: copia de la lista de la asignatura, para que el
  archivo sea legible. La web mantiene los nombres sincronizados.
- `presentado`: valores canónicos `si`, `no` o en blanco (sin marcar). También
  se aceptan, sin distinguir mayúsculas: `sí`, `s`, `x`, `1`, `true`, `yes` y
  `presentado` (= `si`); `n`, `0`, `false`, `np` y `no presentado` (= `no`).
  Un alumno con `presentado = no` tiene nota NP.
- `observaciones`: texto libre.

Ejemplo:

```csv
id,apellidos,nombre,presentado,observaciones
alvarez-lopez-ana,Álvarez López,Ana,si,
martinez-souto-diego,Martínez Souto,Diego,no,
ramos-gil-irene,Ramos Gil,Irene,si,Erasmus
```

## notas/<corrector>.csv

Una hoja de notas por corrector (una persona o un LLM).

Columnas: `id,alumno,<ids de las hojas en el orden de config.json>,total,comentario`.

- `<corrector>`: nombre del corrector, con el patrón `[a-z0-9][a-z0-9_-]*`.
  `final` está reservado.
- `alumno`: `Apellidos, Nombre`. Es informativo y se ignora al leer; la web lo
  rellena desde la lista del examen.
- Una columna por hoja con la nota de ese apartado. Una celda en blanco
  significa «sin corregir».
- `total`: en los modos calculados lo escribe la web para que el archivo sea
  legible; si no coincide con el calculado, es un *aviso* y gana el calculado.
  En modo manual es la nota.
- `comentario`: comentario breve.
- Una fila por alumno corregido.
- El comentario largo (Markdown libre) va en `notas/<corrector>/<id>.md`.

Ejemplo (`notas/pablo.csv`):

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,comentario
alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien
fernandez-rey-carlos,"Fernández Rey, Carlos",1,1,2,1.5,5.5,
garcia-perez-lucia,"García Pérez, Lucía",2,2,,,,
```

Ejemplo de comentario largo (`notas/claude/alvarez-lopez-ana.md`):

```markdown
# Álvarez López, Ana

- Ej. 1: correcto.
- Ej. 2: el planteamiento es correcto, pero hay un error de signo en el resultado final (-0,5).
```

## notas/final.csv

Las notas oficiales antes de revisiones. Igual que una hoja de corrector, con
una columna más, `origen`, después de `comentario`:

- `origen`: el nombre del corrector del que se copió la fila, o `manual` si se
  editó directamente.

Se construye desde la vista de comparación (copiando la fila de un corrector
para cada alumno, o en bloque) o editándola directamente. Al copiar de un
corrector también se copia su `notas/<corrector>/<id>.md` a
`notas/final/<id>.md` si existe.

Ejemplo:

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,comentario,origen
alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien,pablo
fernandez-rey-carlos,"Fernández Rey, Carlos",1,1,2,1.5,5.5,,pablo
```

## revisiones/

Cada sesión de revisión de notas es un archivo
`revisiones/NN-AAAA-MM-DD.csv`, donde `NN` son dos cifras desde `01`.

Columnas: `id,alumno,<ids de las hojas>,total,motivo`.

- Solo aparecen los alumnos revisados.
- Una celda de hoja no vacía es el nuevo valor; una celda en blanco significa
  «sin cambios».
- `total`: en modo manual es la nueva nota (en blanco = sin cambios); en los
  modos calculados es informativo (se recalcula).
- `motivo`: texto libre; no debería estar en blanco.

**Nota vigente** de cada alumno del examen: si `presentado = no`, es NP. Si
no, se toma su fila de `final.csv`, se aplican las revisiones en orden de
nombre de archivo y se calcula. Si no hay fila en ningún sitio, el alumno está
«sin nota».

Ejemplo (`revisiones/01-2026-11-20.csv`):

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,motivo
fernandez-rey-carlos,"Fernández Rey, Carlos",,1.5,,,6,Apartado 1b mal sumado
```

## entregas/

Cada alumno tiene una carpeta `entregas/<id>/` con dos subcarpetas, y cada una
puede contener cualquier número de archivos:

- `entregas/<id>/original/`: la entrega original del alumno.
- `entregas/<id>/corregido/`: la versión corregida.

Una carpeta cuyo nombre no es un `id` de la lista del examen es un *aviso*.

Ejemplo:

```
entregas/
├── alvarez-lopez-ana/
│   ├── original/examen.pdf
│   └── corregido/examen-corregido.pdf
└── fernandez-rey-carlos/
    └── original/examen.pdf
```

## Validación

Correctron nunca se niega a mostrar los datos, pero informa de cada
incoherencia como *error* o *aviso*:

| Nivel | Archivo | Comprobación |
| --- | --- | --- |
| error | asignatura.json | JSON no válido o no es un objeto |
| error | alumnos.csv (asignatura) | falta una columna obligatoria; `id` repetido; `id` en blanco; fila mal formada |
| aviso | alumnos.csv (asignatura) | `id` que no sigue el patrón |
| error | config.json | cualquier regla de config.json (JSON no válido, tipos, ids, estructura) |
| aviso | config.json | suma de máximos ≠ `nota_maxima` en `suma` (solo con criterios); clave desconocida dentro de un criterio |
| error | alumnos.csv (examen) | falta una columna obligatoria; `id` repetido; `id` en blanco; `presentado` no válido; fila mal formada |
| aviso | alumnos.csv (examen) | `id` que no está en la lista de la asignatura |
| error | hoja de notas / final / revisión | falta la columna `id`; `id` repetido; celda no numérica; valor fuera de rango; fila mal formada |
| aviso | hoja de notas / final / revisión | `id` que no está en la lista del examen; nota de un alumno con `presentado = no`; columna desconocida; falta la columna de una hoja; `total` ≠ calculado (modos calculados; en una revisión, sobre el resultado de `final.csv` más las revisiones hasta esa, incluida); nombre de corrector no válido |
| aviso | final.csv | `origen` que no es `manual` ni un corrector existente |
| aviso | revisión | nombre de archivo que no sigue `NN-AAAA-MM-DD.csv`; `motivo` en blanco |
| aviso | entregas/ | carpeta que no está en la lista del examen |

## Instrucciones para un corrector LLM

Si eres un LLM y vas a corregir un examen o trabajo:

1. Lee `config.json` del examen para conocer los criterios, sus `maximo`, la
   `nota_maxima` y el `calculo_total`. Lee el enunciado y la rúbrica de
   `enunciado/` y las entregas de `entregas/<id>/original/`.
2. Escribe tu hoja en `notas/<nombre>.csv`, donde `<nombre>` es tu nombre de
   corrector (minúsculas, cifras, `-` o `_`; nunca `final`).
3. Usa exactamente la cabecera
   `id,alumno,<hojas en orden de config.json>,total,comentario`. Por ejemplo,
   con la configuración de ejemplo: `id,alumno,ej1a,ej1b,ej2,ej3,total,comentario`.
4. Escribe una fila por alumno presentado (los de `alumnos.csv` del examen con
   `presentado` distinto de `no`), con su `id` exacto.
5. Usa punto decimal (`7.5`, no `7,5`) y separador coma. Pon entre comillas
   los valores que contengan comas, como `"Álvarez López, Ana"`.
6. Cada valor debe estar entre `0` y el `maximo` de su hoja. En modo manual,
   `total` debe estar entre `0` y `nota_maxima`.
7. Deja la celda en blanco si no has corregido ese apartado.
8. El comentario largo va en `notas/<nombre>/<id>.md` (Markdown libre); en la
   columna `comentario` pon solo un resumen breve.
9. **Nunca** edites `notas/final.csv`, `alumnos.csv` ni `config.json`.
