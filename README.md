# Correctron

Correctron es una herramienta local para corregir exámenes y trabajos. Guarda
alumnos, criterios, notas de varios correctores, revisiones y entregas en una
carpeta `data/` de archivos CSV, JSON, Markdown y PDF que se pueden editar a
mano (o con un LLM), y ofrece una página web local para gestionarlos.

Los archivos son la única fuente de verdad: no hay base de datos. La web lee
los archivos en cada petición, así que ve al momento lo que cambies con un
editor de texto o lo que escriba un LLM, y nunca sobrescribe en silencio un
cambio hecho fuera de ella.

## Instalación

Hace falta [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Uso

```sh
uv run correctron
```

Abre el navegador en `http://127.0.0.1:8765`. Opciones:

- `--data CARPETA`: carpeta de datos. Si no se indica, se usa la variable de
  entorno `CORRECTRON_DATA` y, si tampoco existe, `./data`.
- `--host` y `--port`: dirección y puerto (por defecto `127.0.0.1` y `8765`).
- `--no-abrir`: no abrir el navegador automáticamente.

### Probar con los datos de ejemplo

```sh
cp -r ejemplo/data /tmp/correctron-demo
uv run correctron --data /tmp/correctron-demo
```

No lo ejecutes directamente sobre `ejemplo/data`: los tests dependen de esos
archivos exactos.

### Qué se puede hacer desde la web

- Crear asignaturas y exámenes o trabajos.
- Añadir, editar, quitar e importar (pegando desde una hoja de cálculo) los
  alumnos de una asignatura; gestionar la lista de cada examen y marcar quién
  se ha presentado.
- Definir los criterios de corrección (con un nivel de subapartados) y cómo se
  calcula la nota: suma, media ponderada o nota manual.
- Subir y ver el enunciado, la rúbrica y la entrega original y corregida de
  cada alumno.
- Poner notas por corrector con el desglose, un comentario corto y un
  comentario largo en Markdown.
- Comparar correctores, ver las discrepancias y construir la nota oficial
  (`final.csv`).
- Registrar revisiones de notas con su motivo y ver la nota vigente.

## Estructura de la carpeta de datos

```
data/
├── LEEME.md                      guía del formato (se crea sola)
├── .papelera/                    archivos borrados desde la web
└── <asignatura>/
    ├── asignatura.json
    ├── alumnos.csv
    └── <examen>/
        ├── config.json           criterios y cálculo de la nota
        ├── alumnos.csv           lista del examen (con «presentado»)
        ├── enunciado/
        ├── entregas/<id>/original/  y  entregas/<id>/corregido/
        ├── notas/<corrector>.csv    una hoja por corrector
        ├── notas/<corrector>/<id>.md  comentarios largos
        ├── notas/final.csv          nota oficial
        └── revisiones/NN-AAAA-MM-DD.csv
```

El formato completo, con todas las columnas y reglas, está en
[`src/correctron/resources/LEEME.md`](src/correctron/resources/LEEME.md). Esa
guía se copia como `LEEME.md` en la carpeta de datos.

## Usar un LLM como corrector

Pide al LLM que lea `data/LEEME.md`, en especial la sección
«Instrucciones para un corrector LLM», y que escriba su hoja en
`notas/<nombre>.csv` (y, si quiere, comentarios largos en
`notas/<nombre>/<id>.md`) dentro de la carpeta del examen. La hoja aparece
como un corrector más en las pestañas «Notas» y «Comparar», desde donde puedes
pasar sus notas a `final.csv`.

## Seguridad y privacidad

- El servidor escucha solo en `127.0.0.1` y no tiene usuarios ni contraseñas:
  es para usarlo en tu ordenador.
- `data/` está en `.gitignore`: los datos de alumnos no deben subirse a un
  repositorio de código. Los datos de `ejemplo/` son ficticios.
- Los archivos borrados desde la web se mueven a `data/.papelera/`, de donde se
  pueden recuperar.
- Cada escritura comprueba que el archivo no ha cambiado desde que se abrió la
  página; si ha cambiado, no se guarda nada y la web pide recargar.

## Desarrollo

- Tests: `uv run pytest`
- Lint: `uv run ruff check` y `uv run ruff format --check`
