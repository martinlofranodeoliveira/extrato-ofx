"""Ponto de entrada para leitura completa, sem efeitos externos."""
from .model import Limits
from .parser import parse_document
from .extract import extract_report


def parse_ofx(raw: bytes, *, limits: Limits = Limits()) -> dict:
    return extract_report(parse_document(raw, limits=limits), limits=limits)
