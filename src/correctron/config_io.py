"""Reading, validating and writing config.json and asignatura.json."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from .fsutil import atomic_write_text
from .models import Criterion, ExamConfig, Issue, Leaf
from .numbers import format_number

RESERVED_COLUMNS = {"id", "alumno", "total", "comentario", "origen", "motivo"}
# `version` is not a CSV column, but the web posts it next to the criterion cells.
RESERVED_IDS = RESERVED_COLUMNS | {"version"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIPOS = ("examen", "trabajo")
_MODOS = ("suma", "ponderada", "manual")
_TOP_KEYS = ("nombre", "tipo", "fecha", "nota_maxima", "decimales", "calculo_total", "criterios")
_CRITERION_KEYS = {"id", "nombre", "maximo", "peso", "subcriterios"}
_LEAF_KEYS = {"id", "nombre", "maximo"}


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _to_decimal(value: int | float) -> Decimal:
    return Decimal(str(value))


class _Parser:
    def __init__(self, file: str):
        self.file = file
        self.issues: list[Issue] = []
        self.seen_ids: set[str] = set()

    def error(self, message: str) -> None:
        self.issues.append(Issue("error", self.file, message))

    def aviso(self, message: str) -> None:
        self.issues.append(Issue("aviso", self.file, message))

    def has_errors(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    def check_id(self, raw: object, where: str) -> str | None:
        if not isinstance(raw, str) or not raw:
            self.error(f"{where}: falta el «id» o no es un texto.")
            return None
        if not ID_RE.match(raw):
            self.error(
                f"{where}: el id «{raw}» no es válido (minúsculas, cifras y «_», "
                "empezando por letra o cifra)."
            )
        elif raw in RESERVED_IDS:
            self.error(f"{where}: el id «{raw}» está reservado.")
        if raw in self.seen_ids:
            self.error(f"{where}: el id «{raw}» está repetido.")
        self.seen_ids.add(raw)
        return raw

    def nombre_of(self, item: dict, default: str, where: str) -> str:
        value = item.get("nombre", default)
        if not isinstance(value, str):
            self.error(f"{where}: «nombre» debe ser un texto.")
            return default
        return value

    def maximo_of(self, item: dict, where: str) -> Decimal | None:
        value = item["maximo"]
        if not _is_number(value) or value <= 0:
            self.error(f"{where}: «maximo» debe ser un número mayor que 0.")
            return None
        return _to_decimal(value)

    def unknown_keys(self, item: dict, allowed: set[str], where: str) -> None:
        for key in item:
            if key not in allowed:
                self.aviso(f"{where}: clave desconocida «{key}»; se eliminará al guardar.")

    def leaf(self, item: object, where: str) -> Leaf | None:
        if not isinstance(item, dict):
            self.error(f"{where}: cada subcriterio debe ser un objeto.")
            return None
        leaf_id = self.check_id(item.get("id"), where)
        label = f"{where} «{leaf_id}»" if leaf_id else where
        nombre = self.nombre_of(item, leaf_id or "", label)
        if "peso" in item:
            self.error(f"{label}: «peso» solo se permite en los criterios de primer nivel.")
        if "subcriterios" in item:
            self.error(f"{label}: solo se permiten dos niveles de criterios.")
        maximo = None
        if "maximo" not in item:
            self.error(f"{label}: falta «maximo».")
        else:
            maximo = self.maximo_of(item, label)
        self.unknown_keys(item, _LEAF_KEYS | {"peso", "subcriterios"}, label)
        if leaf_id is None or maximo is None:
            return None
        return Leaf(leaf_id, nombre, maximo)

    def criterion(self, item: object, index: int) -> Criterion | None:
        where = f"Criterio {index}"
        if not isinstance(item, dict):
            self.error(f"{where}: cada criterio debe ser un objeto.")
            return None
        crit_id = self.check_id(item.get("id"), where)
        label = f"Criterio «{crit_id}»" if crit_id else where
        nombre = self.nombre_of(item, crit_id or "", label)
        peso = Decimal(1)
        if "peso" in item:
            raw = item["peso"]
            if not _is_number(raw) or raw < 0:
                self.error(f"{label}: «peso» debe ser un número mayor o igual que 0.")
            else:
                peso = _to_decimal(raw)
        self.unknown_keys(item, _CRITERION_KEYS, label)
        has_max = "maximo" in item
        has_subs = "subcriterios" in item
        maximo: Decimal | None = None
        subs: list[Leaf] = []
        if has_max and has_subs:
            self.error(f"{label}: no puede tener «maximo» y «subcriterios» a la vez.")
        elif not has_max and not has_subs:
            self.error(f"{label}: necesita «maximo» (apartado) o «subcriterios» (grupo).")
        elif has_max:
            maximo = self.maximo_of(item, label)
        else:
            raw_subs = item["subcriterios"]
            if not isinstance(raw_subs, list) or not raw_subs:
                self.error(f"{label}: «subcriterios» debe ser una lista no vacía.")
            else:
                for n, sub in enumerate(raw_subs, start=1):
                    leaf = self.leaf(sub, f"{label}, subcriterio {n}")
                    if leaf is not None:
                        subs.append(leaf)
        if crit_id is None:
            return None
        return Criterion(crit_id, nombre, peso, maximo, subs)


def parse_exam_config(data: object, file: str) -> tuple[ExamConfig | None, list[Issue]]:
    """Validate a decoded config.json. Never raises on bad input."""
    p = _Parser(file)
    if not isinstance(data, dict):
        p.error("config.json debe ser un objeto JSON.")
        return None, p.issues

    folder = PurePosixPath(file.replace("\\", "/")).parent.name
    nombre = data.get("nombre", folder)
    if not isinstance(nombre, str):
        p.error("«nombre» debe ser un texto.")
        nombre = folder

    tipo = data.get("tipo", "examen")
    if tipo not in _TIPOS:
        p.error(f"«tipo» debe ser «examen» o «trabajo» (es {json.dumps(tipo)}).")

    fecha = data.get("fecha", "")
    if not isinstance(fecha, str) or (fecha and not _valid_date(fecha)):
        p.error(f"«fecha» debe tener la forma AAAA-MM-DD o estar vacía (es {json.dumps(fecha)}).")
        fecha = ""

    nota_maxima = Decimal(10)
    raw_nm = data.get("nota_maxima", 10)
    if not _is_number(raw_nm) or raw_nm <= 0:
        p.error("«nota_maxima» debe ser un número mayor que 0.")
    else:
        nota_maxima = _to_decimal(raw_nm)

    decimales = data.get("decimales", 2)
    if not isinstance(decimales, int) or isinstance(decimales, bool) or not 0 <= decimales <= 4:
        p.error("«decimales» debe ser un entero entre 0 y 4.")
        decimales = 2

    calculo = data.get("calculo_total", "suma")
    if calculo not in _MODOS:
        p.error(
            f"«calculo_total» debe ser «suma», «ponderada» o «manual» (es {json.dumps(calculo)})."
        )

    criterios: list[Criterion] = []
    raw_crit = data.get("criterios", [])
    if not isinstance(raw_crit, list):
        p.error("«criterios» debe ser una lista.")
    else:
        for index, item in enumerate(raw_crit, start=1):
            crit = p.criterion(item, index)
            if crit is not None:
                criterios.append(crit)

    if not p.has_errors() and criterios:
        if calculo == "suma":
            total = sum((leaf.maximo for c in criterios for leaf in c.leaves()), Decimal(0))
            if total != nota_maxima:
                p.aviso(
                    f"La suma de los máximos de los apartados ({format_number(total)}) no "
                    f"coincide con la nota máxima ({format_number(nota_maxima)})."
                )
        elif calculo == "ponderada" and sum((c.peso for c in criterios), Decimal(0)) == 0:
            p.error("En «ponderada» la suma de los pesos no puede ser 0.")

    if p.has_errors():
        return None, p.issues

    extra = {k: v for k, v in data.items() if k not in _TOP_KEYS}
    cfg = ExamConfig(
        nombre=nombre,
        tipo=tipo,
        fecha=fecha,
        nota_maxima=nota_maxima,
        decimales=decimales,
        calculo_total=calculo,
        criterios=criterios,
        extra=extra,
    )
    return cfg, p.issues


def _valid_date(text: str) -> bool:
    if not _DATE_RE.match(text):
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def load_exam_config(path: Path, file: str) -> tuple[ExamConfig | None, list[Issue]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, [Issue("error", file, "No existe config.json.")]
    except UnicodeDecodeError as exc:
        return None, [Issue("error", file, f"JSON no válido: {exc}")]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [Issue("error", file, f"JSON no válido: {exc}")]
    return parse_exam_config(data, file)


def _json_number(d: Decimal) -> int | float:
    if d == d.to_integral_value():
        return int(d)
    return float(format_number(d))


def exam_config_to_dict(cfg: ExamConfig) -> dict[str, Any]:
    criterios: list[dict[str, Any]] = []
    for c in cfg.criterios:
        item: dict[str, Any] = {"id": c.id, "nombre": c.nombre}
        if c.is_group:
            item["peso"] = _json_number(c.peso)
            item["subcriterios"] = [
                {"id": leaf.id, "nombre": leaf.nombre, "maximo": _json_number(leaf.maximo)}
                for leaf in c.subcriterios
            ]
        else:
            assert c.maximo is not None
            item["maximo"] = _json_number(c.maximo)
            item["peso"] = _json_number(c.peso)
        criterios.append(item)
    result: dict[str, Any] = {
        "nombre": cfg.nombre,
        "tipo": cfg.tipo,
        "fecha": cfg.fecha,
        "nota_maxima": _json_number(cfg.nota_maxima),
        "decimales": cfg.decimales,
        "calculo_total": cfg.calculo_total,
        "criterios": criterios,
    }
    for key, value in cfg.extra.items():
        if key not in result:
            result[key] = value
    return result


def _dump_json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def save_exam_config(path: Path, cfg: ExamConfig) -> None:
    atomic_write_text(path, _dump_json(exam_config_to_dict(cfg)))


def default_exam_config(nombre: str, tipo: str, fecha: str) -> ExamConfig:
    return ExamConfig(
        nombre=nombre,
        tipo=tipo,  # type: ignore[arg-type]
        fecha=fecha,
        nota_maxima=Decimal(10),
        decimales=2,
        calculo_total="suma",
        criterios=[],
        extra={},
    )


def load_subject_meta(path: Path, default_name: str) -> tuple[dict, list[Issue]]:
    """Read asignatura.json; missing keys get defaults. Unknown keys are kept."""
    defaults = {"nombre": default_name, "curso": "", "codigo": ""}
    file = f"{path.parent.name}/{path.name}"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return dict(defaults), []
    except UnicodeDecodeError as exc:
        return dict(defaults), [Issue("error", file, f"JSON no válido: {exc}")]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return dict(defaults), [Issue("error", file, f"JSON no válido: {exc}")]
    if not isinstance(data, dict):
        return dict(defaults), [Issue("error", file, "asignatura.json debe ser un objeto JSON.")]
    meta = dict(data)
    for key, value in defaults.items():
        if not isinstance(meta.get(key), str) or (key == "nombre" and not meta[key].strip()):
            meta[key] = value
    return meta, []


def save_subject_meta(path: Path, meta: dict) -> None:
    atomic_write_text(path, _dump_json(meta))
