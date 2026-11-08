"""Transporte OFX limitado, sem reparos silenciosos da entrada.

O leitor SGML é original; o XML usa somente a API pública do defusedxml.
As árvores intermediárias não contêm objetos do parser XML.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import DefusedXMLParser

from .model import Header, Limits, Node, OfxError, ParsedDocument, ParseStats


_SPACE = " \t\r\n"
_SGML_VERSIONS = {"102", "103", "151", "160"}
_XML_VERSIONS = {"200", "201", "202", "203", "210", "211", "220", "221"}
_SGML_KEYS = {
    "OFXHEADER", "DATA", "VERSION", "SECURITY", "ENCODING", "CHARSET",
    "COMPRESSION", "OLDFILEUID", "NEWFILEUID",
}
_PI_KEYS = {"OFXHEADER", "VERSION", "SECURITY", "OLDFILEUID", "NEWFILEUID"}
_CODECS = {
    ("USASCII", "1252"): "cp1252",
    ("USASCII", "ISO-8859-1"): "latin-1",
    ("USASCII", "8859-1"): "latin-1",
    ("USASCII", "NONE"): "ascii",
    ("UTF-8", "NONE"): "utf-8",
    ("UTF-8", "UTF-8"): "utf-8",
}
_AGGREGATES = frozenset("""
OFX SIGNONMSGSRSV1 SONRS STATUS FI BANKMSGSRSV1 STMTTRNRS STMTRS
BANKACCTFROM BANKACCTTO BANKTRANLIST STMTTRN LEDGERBAL AVAILBAL
CREDITCARDMSGSRSV1 CCSTMTTRNRS CCSTMTRS CCACCTFROM CCACCTTO
PAYEE CURRENCY ORIGCURRENCY
""".split())
_LEAVES = frozenset("""
CODE SEVERITY MESSAGE DTSERVER LANGUAGE DTPROFUP DTACCTUP USERKEY
TSKEYEXPIRE SESSCOOKIE ACCESSKEY INTU.BID ORG FID TRNUID CLTCOOKIE
CURDEF BANKID BRANCHID ACCTID ACCTTYPE ACCTKEY DTSTART DTEND
TRNTYPE DTPOSTED DTUSER DTAVAIL TRNAMT FITID NAME MEMO CHECKNUM
REFNUM SRVRTID SIC PAYEEID CORRECTFITID CORRECTACTION BALAMT DTASOF
MKTGINFO ADDR1 ADDR2 ADDR3 CITY STATE POSTALCODE COUNTRY PHONE
CURRENCYRATE CURSYM CURRENCYID DTEXPIRE USERID USERPASS
""".split())
_TAG = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_INVALID_CHAR = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_ATTRIBUTE = re.compile(r'''([A-Za-z][A-Za-z0-9_.-]*)[ \t\r\n]*=[ \t\r\n]*(["'])(.*?)\2''', re.DOTALL | re.ASCII)


def _fail(code: str) -> None:
    raise OfxError(code, "Transporte OFX fora do perfil suportado.")


def _white(value: str) -> bool:
    return not value.strip(_SPACE)


def _attributes(value: str) -> dict[str, str]:
    """Atributos de cabeçalho; nunca aceitar duplicatas ou lixo entre eles."""
    result: dict[str, str] = {}
    pos = 0
    while pos < len(value):
        if value[pos] not in _SPACE:
            _fail("invalid_header")
        while pos < len(value) and value[pos] in _SPACE:
            pos += 1
        if pos == len(value):
            break
        match = _ATTRIBUTE.match(value, pos)
        if match is None:
            _fail("invalid_header")
        key, _, item = match.groups()
        if key in result:
            _fail("duplicate_header")
        if not item or any(ord(c) < 32 or ord(c) > 126 for c in item):
            _fail("invalid_header")
        result[key] = item
        pos = match.end()
    return result


def _sgml_header(raw: bytes, limits: Limits) -> tuple[Header, str]:
    start = raw.find(b"<")
    if start < 0:
        _fail("invalid_header")
    try:
        header_text = raw[:start].decode("ascii")
    except UnicodeError:
        _fail("invalid_header")
    if any(ord(c) < 32 and c not in _SPACE for c in header_text):
        _fail("invalid_header")
    values: dict[str, str] = {}
    for line in re.split(r"\r\n|\r|\n", header_text):
        line = line.strip(_SPACE)
        if not line:
            continue
        key, separator, value = line.partition(":")
        value = value.strip(_SPACE)
        if not separator or key not in _SGML_KEYS or not value:
            _fail("invalid_header")
        if key in values:
            _fail("duplicate_header")
        if len(value) > 4096:
            _fail("text_limit")
        values[key] = value
    if values.keys() != _SGML_KEYS:
        _fail("missing_header")
    if values["OFXHEADER"] != "100" or values["DATA"] != "OFXSGML":
        _fail("unsupported_header")
    if values["VERSION"] not in _SGML_VERSIONS:
        _fail("unsupported_version")
    if values["SECURITY"] != "NONE" or values["COMPRESSION"] != "NONE":
        _fail("unsupported_security")
    codec = _CODECS.get((values["ENCODING"].upper(), values["CHARSET"].upper()))
    if codec is None:
        _fail("unsupported_encoding")
    try:
        body = raw[start:].decode(codec, errors="strict")
    except UnicodeError:
        _fail("invalid_encoding")
    return Header("sgml", values["VERSION"], codec), body


def _xml_header(raw: bytes, limits: Limits) -> tuple[Header, bytes]:
    end = raw.find(b"?>")
    if end < 0:
        _fail("invalid_header")
    try:
        declaration = raw[:end + 2].decode("ascii")
    except UnicodeError:
        _fail("invalid_header")
    if not declaration.startswith("<?xml"):
        _fail("invalid_header")
    attrs = _attributes(declaration[5:-2])
    if not {"version"} <= attrs.keys() <= {"version", "encoding", "standalone"}:
        _fail("invalid_header")
    if attrs["version"] != "1.0" or attrs.get("standalone", "no") not in {"yes", "no"}:
        _fail("unsupported_header")
    encoding = attrs.get("encoding", "UTF-8").upper()
    if encoding not in {"UTF-8", "US-ASCII"}:
        _fail("unsupported_encoding")
    cursor = end + 2
    while cursor < len(raw) and raw[cursor] in b" \t\r\n":
        cursor += 1
    if not raw.startswith(b"<?OFX", cursor):
        _fail("missing_header")
    pi_end = raw.find(b"?>", cursor)
    if pi_end < 0:
        _fail("invalid_header")
    try:
        pi_text = raw[cursor + 5:pi_end].decode("ascii")
    except UnicodeError:
        _fail("invalid_header")
    values = _attributes(pi_text)
    if values.keys() != _PI_KEYS:
        _fail("invalid_header")
    if any(len(value) > 4096 for value in values.values()):
        _fail("text_limit")
    if values["OFXHEADER"] != "200":
        _fail("unsupported_header")
    if values["VERSION"] not in _XML_VERSIONS:
        _fail("unsupported_version")
    if values["SECURITY"] != "NONE":
        _fail("unsupported_security")
    # Remove only the already validated transport PI. Expat validates the XML
    # declaration's order/syntax and the remaining document independently.
    xml = raw[:end + 2] + raw[pi_end + 2:]
    return Header("xml", values["VERSION"], "utf-8" if encoding == "UTF-8" else "ascii"), xml


@dataclass
class _Frame:
    tag: str
    chunks: list[str] = field(default_factory=list)
    chars: int = 0
    meaningful: bool = False
    children: list[Node] = field(default_factory=list)


class _XMLTarget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.stack: list[_Frame] = []
        self.root: Node | None = None
        self.nodes = self.depth = self.text_chars = 0

    def start(self, tag: str, attrs: dict) -> None:
        if "{" in tag or ":" in tag:
            _fail("unsupported_namespace")
        if not _TAG.fullmatch(tag) or tag != tag.upper():
            _fail("invalid_tag")
        if attrs:
            _fail("unsupported_attributes")
        if len(self.stack) >= self.limits.max_depth:
            _fail("depth_limit")
        if self.nodes >= self.limits.max_nodes:
            _fail("node_limit")
        if self.stack:
            parent = self.stack[-1]
            if parent.meaningful:
                _fail("mixed_content")
            parent.chunks.clear()
        elif self.root is not None:
            _fail("multiple_roots")
        self.nodes += 1
        self.stack.append(_Frame(tag))
        self.depth = max(self.depth, len(self.stack))

    def end(self, tag: str) -> None:
        if not self.stack or self.stack[-1].tag != tag:
            _fail("malformed_xml")
        current = self.stack.pop()
        if not current.children and current.chars > self.limits.max_text_chars:
            _fail("text_limit")
        text = "" if current.children else "".join(current.chunks)
        node = Node(tag, text, tuple(current.children))
        if self.stack:
            self.stack[-1].children.append(node)
        else:
            self.root = node

    def data(self, value: str) -> None:
        self.text_chars += len(value)
        if not self.stack:
            if not _white(value):
                _fail("malformed_xml")
            return
        current = self.stack[-1]
        if current.children:
            if not _white(value):
                _fail("mixed_content")
            return
        current.chars += len(value)
        current.meaningful = current.meaningful or not _white(value)
        if current.meaningful and current.chars > self.limits.max_text_chars:
            _fail("text_limit")
        # Formatting before a first child may exceed a leaf budget. Keep at
        # most that budget; a later non-space or leaf close will reject it.
        if current.chars <= self.limits.max_text_chars:
            current.chunks.append(value)

    def start_ns(self, prefix: str | None, uri: str) -> None:
        _fail("unsupported_namespace")

    def pi(self, target: str, text: str | None) -> None:
        _fail("unsupported_processing_instruction")

    def comment(self, text: str) -> None:
        pass

    def close(self) -> Node:
        if self.root is None or self.stack:
            _fail("malformed_xml")
        if self.root.tag != "OFX":
            _fail("invalid_root")
        return self.root


def _parse_xml(raw: bytes, limits: Limits) -> tuple[Node, ParseStats]:
    target = _XMLTarget(limits)
    parser = DefusedXMLParser(
        target=target, forbid_dtd=True, forbid_entities=True, forbid_external=True,
    )
    try:
        for offset in range(0, len(raw), 8192):
            parser.feed(raw[offset:offset + 8192])
        root = parser.close()
    except OfxError:
        raise
    except DefusedXmlException:
        _fail("unsafe_xml")
    except (ParseError, UnicodeError, ValueError):
        _fail("malformed_xml")
    return root, ParseStats(target.nodes, target.depth, target.text_chars)


def _xml_character(number: int) -> bool:
    return number in {9, 10, 13} or 0x20 <= number <= 0xD7FF or 0xE000 <= number <= 0xFFFD or 0x10000 <= number <= 0x10FFFF


def _decoded_parts(text: str):
    """Decodificação única, sem entidades HTML ou expansão recursiva."""
    if _INVALID_CHAR.search(text):
        _fail("invalid_character")
    cursor = 0
    predefined = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
    while cursor < len(text):
        amp = text.find("&", cursor)
        if amp < 0:
            chunk, cursor = text[cursor:], len(text)
        elif amp > cursor:
            chunk, cursor = text[cursor:amp], amp
        else:
            semi = text.find(";", amp + 1, amp + 14)
            if semi < 0:
                _fail("invalid_entity")
            entity = text[amp + 1:semi]
            chunk = predefined.get(entity)
            if chunk is None:
                if re.fullmatch(r"#[0-9]{1,10}", entity, re.ASCII):
                    number = int(entity[1:], 10)
                elif re.fullmatch(r"#x[0-9a-fA-F]{1,8}", entity, re.ASCII):
                    number = int(entity[2:], 16)
                else:
                    _fail("invalid_entity")
                if not _xml_character(number):
                    _fail("invalid_character")
                chunk = chr(number)
            cursor = semi + 1
        yield chunk


def _decode_entities(text: str, budget: int) -> str:
    parts: list[str] = []
    count = 0
    for chunk in _decoded_parts(text):
        count += len(chunk)
        if count > budget:
            _fail("text_limit")
        parts.append(chunk)
    return "".join(parts)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


class _SGMLReader:
    """Scanner com um token de antecipação; agregados exigem fechamento."""
    def __init__(self, body: str, limits: Limits):
        self.body, self.limits = body, limits
        self.cursor = 0
        self.pending: _Token | None = None
        self.nodes = self.depth = self.text_chars = 0

    def _scan(self) -> _Token:
        if self.cursor >= len(self.body):
            return _Token("eof", "")
        if self.body[self.cursor] != "<":
            end = self.body.find("<", self.cursor)
            if end < 0:
                end = len(self.body)
            text = self.body[self.cursor:end]
            self.cursor = end
            return _Token("text", text)
        end = self.body.find(">", self.cursor + 1)
        if end < 0:
            _fail("malformed_sgml")
        value = self.body[self.cursor + 1:end]
        self.cursor = end + 1
        if value.startswith(("!", "?")):
            _fail("unsafe_markup")
        closing = value.startswith("/")
        tag = (value[1:] if closing else value).rstrip(_SPACE)
        if ":" in tag:
            _fail("unsupported_namespace")
        if not _TAG.fullmatch(tag):
            _fail("invalid_tag")
        return _Token("end" if closing else "start", tag.upper())

    def peek(self) -> _Token:
        if self.pending is None:
            self.pending = self._scan()
        return self.pending

    def take(self) -> _Token:
        token = self.peek()
        self.pending = None
        return token

    def text(self, budget: int) -> str:
        token = self.take()
        if token.kind != "text":
            _fail("malformed_sgml")
        value = _decode_entities(token.value, budget)
        self.text_chars += len(value)
        return value

    def prefix(self) -> tuple[str, int, bool]:
        """Texto de extensão: não acumular um prefixo de formatação enorme."""
        token = self.take()
        parts: list[str] = []
        count = 0
        meaningful = False
        for chunk in _decoded_parts(token.value):
            count += len(chunk)
            meaningful = meaningful or not _white(chunk)
            if meaningful and count > self.limits.max_text_chars:
                _fail("text_limit")
            if count <= self.limits.max_text_chars:
                parts.append(chunk)
        self.text_chars += count
        return "".join(parts), count, meaningful

    def whitespace(self) -> None:
        """Consumir formatação de agregado sem montar uma string grande."""
        token = self.take()
        for chunk in _decoded_parts(token.value):
            self.text_chars += len(chunk)
            if not _white(chunk):
                _fail("mixed_content")

    def node(self, tag: str, depth: int) -> Node:
        if depth > self.limits.max_depth:
            _fail("depth_limit")
        if self.nodes >= self.limits.max_nodes:
            _fail("node_limit")
        self.nodes += 1
        self.depth = max(self.depth, depth)
        if tag in _LEAVES:
            return self.leaf(tag)
        if tag in _AGGREGATES:
            return self.aggregate(tag, depth)
        # An extension with non-space text is an unclosed SGML leaf. An empty
        # extension can be inferred only from an explicit close or child tree.
        prefix = ""
        prefix_chars = 0
        meaningful = False
        if self.peek().kind == "text":
            prefix, prefix_chars, meaningful = self.prefix()
        token = self.peek()
        if meaningful:
            return self.leaf(tag, prefix)
        if token.kind == "end" and token.value == tag:
            self.take()
            if prefix_chars > self.limits.max_text_chars:
                _fail("text_limit")
            return Node(tag, prefix)
        if token.kind == "start":
            return self.aggregate(tag, depth)
        _fail("sgml_ambiguous")

    def leaf(self, tag: str, prefix: str | None = None) -> Node:
        text = prefix if prefix is not None else ""
        if prefix is None and self.peek().kind == "text":
            text = self.text(self.limits.max_text_chars)
        token = self.peek()
        if token.kind == "end" and token.value == tag:
            self.take()
        return Node(tag, text)

    def aggregate(self, tag: str, depth: int) -> Node:
        children: list[Node] = []
        while True:
            token = self.peek()
            if token.kind == "text":
                self.whitespace()
            elif token.kind == "start":
                children.append(self.node(self.take().value, depth + 1))
            elif token.kind == "end":
                if token.value != tag:
                    _fail("mismatched_aggregate")
                self.take()
                return Node(tag, "", tuple(children))
            else:
                _fail("unclosed_aggregate")

    def parse(self) -> tuple[Node, ParseStats]:
        if self.peek().kind == "text":
            self.whitespace()
        first = self.take()
        if first.kind != "start" or first.value != "OFX":
            _fail("invalid_root")
        root = self.node(first.value, 1)
        if self.peek().kind == "text":
            self.whitespace()
        if self.take().kind != "eof":
            _fail("trailing_content")
        return root, ParseStats(self.nodes, self.depth, self.text_chars)


def parse_document(raw: bytes, *, limits: Limits = Limits()) -> ParsedDocument:
    """Analisa bytes OFX; nunca tenta adivinhar ou reparar o encoding."""
    if type(raw) is not bytes:
        _fail("invalid_input_type")
    if not isinstance(limits, Limits):
        _fail("invalid_limits")
    if len(raw) > limits.max_input_bytes:
        _fail("input_limit")
    if not raw:
        _fail("empty_input")
    data = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
    if data.startswith(b"<?xml"):
        header, xml = _xml_header(data, limits)
        root, stats = _parse_xml(xml, limits)
    else:
        if data is not raw:
            _fail("unsupported_bom")
        header, body = _sgml_header(data, limits)
        root, stats = _SGMLReader(body, limits).parse()
    return ParsedDocument(header, root, stats)
