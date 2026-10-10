"""Home page: the list of subjects and the form to create one."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .deps import RepoDep, render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, repo: RepoDep) -> HTMLResponse:
    return render(request, "index.html", asignaturas=repo.list_subjects(), raiz=repo.root)


@router.post("/asignaturas")
def create_subject(
    repo: RepoDep,
    nombre: Annotated[str, Form()] = "",
    curso: Annotated[str, Form()] = "",
) -> RedirectResponse:
    slug = repo.create_subject(nombre, curso)
    return RedirectResponse(f"/a/{slug}", status_code=303)
