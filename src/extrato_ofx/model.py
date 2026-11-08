"""Tipos e orçamento de recursos do leitor local."""
from dataclasses import dataclass, asdict


class OfxError(ValueError):
    def __init__(self, code: str, message: str = "Entrada fora do perfil suportado.", path: str | None = None):
        self.code, self.message, self.path = code, message, path
        super().__init__(message)


@dataclass(frozen=True)
class Limits:
    max_input_bytes: int = 8 * 1024 * 1024
    max_nodes: int = 200_000
    max_depth: int = 64
    max_statements: int = 50
    max_transactions: int = 10_000
    max_text_chars: int = 4096
    max_output_bytes: int = 16 * 1024 * 1024

    def __post_init__(self):
        caps = (16 * 1024 * 1024, 400_000, 128, 200, 100_000, 65536, 32 * 1024 * 1024)
        for (name, value), cap in zip(asdict(self).items(), caps):
            if type(value) is not int or not 1 <= value <= cap:
                raise OfxError("invalid_limits", "Limite inválido.")


@dataclass(frozen=True)
class Node:
    tag: str
    text: str = ""
    children: tuple["Node", ...] = ()


@dataclass(frozen=True)
class Header:
    dialect: str
    version: str
    encoding: str


@dataclass(frozen=True)
class ParseStats:
    nodes: int
    max_depth: int
    text_characters: int


@dataclass(frozen=True)
class ParsedDocument:
    header: Header
    root: Node
    stats: ParseStats
