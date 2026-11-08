"""Leitura local de extratos OFX bancários e de cartão."""
from .model import Limits, OfxError
from .api import parse_ofx
from .report import to_json, to_csv, to_markdown

__version__ = "1.0.0"
__all__ = ["parse_ofx", "Limits", "OfxError", "to_json", "to_csv", "to_markdown", "__version__"]
