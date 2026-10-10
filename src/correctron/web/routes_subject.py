"""Subject page: students, exams, metadata and problems."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..fsutil import tree_fingerprint
from ..repo import BadRequest, Repository
from ..validation import validate_exam, validate_subject
from .deps import SUBJECT_TABS, RepoDep, aviso_oob, estado_oob, fragment, render, render_str

router = APIRouter()


def _subject_dir(repo: Repository, s: str):
    repo.subject_meta(s)  # raises NotFound for an unknown subject
    return repo.root / s


def _panel(request: Request, repo: Repository, s: str, **extra) -> str:
    return render_str(request, "_panel_alumnos.html", s=s, sl=repo.students(s), **extra)


def _count_oob(repo: Repository, s: str) -> str:
    """Out-of-band refresh of the number on the «Alumnos» tab after a structural change."""
    n = len(repo.students(s).students)
    return f'<span id="cuenta-alumnos" class="cuenta" hx-swap-oob="true">{n}</span>'


def _exam_problems(repo: Repository, s: str) -> list[dict]:
    rows = []
    for exam in repo.list_exams(s):
        issues = validate_exam(repo.root, s, exam.slug)
        rows.append(
            {
                "exam": exam,
                "errores": sum(1 for i in issues if i.level == "error"),
                "avisos": sum(1 for i in issues if i.level == "aviso"),
            }
        )
    return rows


@router.get("/a/{s}", response_class=HTMLResponse)
def subject_page(
    repo: RepoDep,
    request: Request,
    s: str,
    tab: str = "alumnos",
    ok: str = "",
) -> HTMLResponse:
    meta, meta_issues, meta_version = repo.subject_meta(s)
    if tab not in SUBJECT_TABS:
        tab = "alumnos"
    folder = repo.root / s
    sl = repo.students(s)
    exams = repo.list_exams(s)
    subject_issues = validate_subject(repo.root, s)
    problems = _exam_problems(repo, s)
    n_problemas = len(subject_issues) + sum(p["errores"] + p["avisos"] for p in problems)
    avisos = [("ok", "Datos guardados.")] if ok == "datos" else []
    return render(
        request,
        "asignatura.html",
        tab=tab,
        s=s,
        meta=meta,
        meta_version=meta_version,
        sl=sl,
        examenes=exams,
        problemas_asignatura=subject_issues,
        problemas_examenes=problems,
        n_problemas=n_problemas,
        huella=tree_fingerprint(folder),
        ruta_vigilada=s,
        avisos_iniciales=avisos,
    )


@router.post("/a/{s}/alumnos/{id}", response_class=HTMLResponse)
def edit_student(
    repo: RepoDep,
    request: Request,
    s: str,
    id: str,
    apellidos: Annotated[str, Form()] = "",
    nombre: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    observaciones: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Inline edit of one student (D26): only out-of-band state comes back."""
    folder = _subject_dir(repo, s)
    try:
        repo.update_student(s, id, apellidos, nombre, email, observaciones, version)
    except BadRequest as exc:
        # Nothing was written: put the stored names back and say why.
        sl = repo.students(s)
        student = next(st for st in sl.students if st.id == id)
        restore = render_str(
            request, "_campos_alumno_oob.html", s=s, st=student, campos=["apellidos", "nombre"]
        )
        return fragment(
            "",
            restore,
            estado_oob(request, folder, "version-lista", sl.version),
            aviso_oob(request, "error", str(exc)),
        )
    return fragment("", estado_oob(request, folder, "version-lista", repo.students(s).version))


@router.post("/a/{s}/alumnos", response_class=HTMLResponse)
def add_student(
    repo: RepoDep,
    request: Request,
    s: str,
    apellidos: Annotated[str, Form()] = "",
    nombre: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    folder = _subject_dir(repo, s)
    new_id = repo.add_student(s, apellidos, nombre, email, version)
    return fragment(
        _panel(request, repo, s, resaltar=[new_id], enfocar_alta=True),
        estado_oob(request, folder),
        _count_oob(repo, s),
        aviso_oob(request, "ok", f"Añadido: {apellidos.strip()}, {nombre.strip()} ({new_id})."),
    )


@router.post("/a/{s}/importar-alumnos", response_class=HTMLResponse)
def import_students(
    repo: RepoDep,
    request: Request,
    s: str,
    texto: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    folder = _subject_dir(repo, s)
    new_ids, errors = repo.import_students(s, texto, version)
    if errors:
        mensaje = "No se ha importado nada. " + " ".join(errors)
        return fragment(
            _panel(request, repo, s, texto_import=texto, import_abierto=True),
            estado_oob(request, folder),
            aviso_oob(request, "error", mensaje),
        )
    if not new_ids:
        return fragment(
            _panel(request, repo, s, import_abierto=True),
            estado_oob(request, folder),
            aviso_oob(request, "info", "No hay ninguna línea que importar."),
        )
    n = len(new_ids)
    mensaje = f"{n} alumno importado." if n == 1 else f"{n} alumnos importados."
    return fragment(
        _panel(request, repo, s, resaltar=new_ids),
        estado_oob(request, folder),
        _count_oob(repo, s),
        aviso_oob(request, "ok", mensaje),
    )


@router.post("/a/{s}/alumnos/{id}/borrar", response_class=HTMLResponse)
def remove_student(
    repo: RepoDep,
    request: Request,
    s: str,
    id: str,
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    folder = _subject_dir(repo, s)
    exams = repo.remove_student(s, id, version)
    if exams:
        aviso = aviso_oob(
            request,
            "info",
            f"«{id}» se ha quitado de la asignatura, pero sigue en la lista de: "
            f"{', '.join(exams)}. Sus notas y entregas se conservan.",
        )
    else:
        aviso = aviso_oob(request, "ok", f"«{id}» se ha quitado de la asignatura.")
    return fragment(
        _panel(request, repo, s), estado_oob(request, folder), _count_oob(repo, s), aviso
    )


@router.post("/a/{s}/examenes")
def create_exam(
    repo: RepoDep,
    s: str,
    nombre: Annotated[str, Form()] = "",
    tipo: Annotated[str, Form()] = "examen",
    fecha: Annotated[str, Form()] = "",
    copiar_alumnos: Annotated[str, Form()] = "",
) -> RedirectResponse:
    exam = repo.create_exam(s, nombre, tipo, fecha, bool(copiar_alumnos))
    return RedirectResponse(f"/a/{s}/e/{exam}?tab=config", status_code=303)


@router.post("/a/{s}/datos")
def save_subject_data(
    repo: RepoDep,
    s: str,
    nombre: Annotated[str, Form()] = "",
    curso: Annotated[str, Form()] = "",
    codigo: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
) -> RedirectResponse:
    repo.update_subject_meta(s, nombre, curso, codigo, version)
    return RedirectResponse(f"/a/{s}?tab=datos&ok=datos", status_code=303)
