"""Domain dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class Issue:
    """A validation finding. `file` is relative to the data root; `message` in Spanish."""

    level: Literal["error", "aviso"]
    file: str
    message: str


@dataclass
class Leaf:
    id: str
    nombre: str
    maximo: Decimal


@dataclass
class Criterion:
    id: str
    nombre: str
    peso: Decimal
    maximo: Decimal | None
    subcriterios: list[Leaf] = field(default_factory=list)

    @property
    def is_group(self) -> bool:
        return bool(self.subcriterios)

    def leaves(self) -> list[Leaf]:
        if self.is_group:
            return list(self.subcriterios)
        assert self.maximo is not None
        return [Leaf(self.id, self.nombre, self.maximo)]


@dataclass
class ExamConfig:
    nombre: str
    tipo: Literal["examen", "trabajo"]
    fecha: str
    nota_maxima: Decimal
    decimales: int
    calculo_total: Literal["suma", "ponderada", "manual"]
    criterios: list[Criterion] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def leaves(self) -> list[Leaf]:
        return [leaf for criterion in self.criterios for leaf in criterion.leaves()]

    def leaf_ids(self) -> list[str]:
        return [leaf.id for leaf in self.leaves()]

    def leaf(self, id: str) -> Leaf | None:
        for leaf in self.leaves():
            if leaf.id == id:
                return leaf
        return None

    def effective_mode(self) -> str:
        return "manual" if not self.criterios else self.calculo_total


@dataclass
class Student:
    id: str
    apellidos: str
    nombre: str
    email: str = ""
    observaciones: str = ""
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class RosterEntry:
    id: str
    apellidos: str
    nombre: str
    presentado: str
    observaciones: str = ""
    extra: dict[str, str] = field(default_factory=dict)
