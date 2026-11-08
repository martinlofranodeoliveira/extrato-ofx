"""Compare somente fixtures inventadas com o ofxtools opcional e fixado.

Este adaptador é original. Ele chama a API pública do projeto independente;
não incorpora código, fixtures ou algoritmos de ofxtools.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
import json
from pathlib import Path
import re


PROJECT = Path(__file__).resolve().parents[1]
ORACLE_VERSION = "1.1.1"


def utc(value: str) -> datetime:
    """O formato ISO pertence à saída; nenhuma regra OFX é reimplementada aqui."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


BANK_EXPECTED = {
    "institution": {"organization": "Banco Fictício Exemplo", "id": "FICTICIO-001"},
    "statements": [{
        "kind": "bank", "currency": "BRL",
        "account": {"bankId": "000000001", "branchId": "0001", "accountId": "CONTA-FICTICIA-001", "accountType": "CHECKING", "accountKey": None},
        "range": [utc("2026-11-01T00:00:00Z"), utc("2026-12-01T00:00:00Z")],
        "rows": [
            {"type": "CREDIT", "amount": Decimal("1500.25"), "fitId": "FIC-BANCO-001", "posted": utc("2026-11-02T12:30:00.125Z"), "name": "Depósito fictício", "memo": "Exemplo sem vínculo bancário"},
            {"type": "DEBIT", "amount": Decimal("-25.75"), "fitId": "FIC-BANCO-002", "posted": utc("2026-11-03T15:15:00Z"), "name": "Café de demonstração", "memo": "Pagamento fictício"},
        ],
        "ledger": [Decimal("2474.50"), utc("2026-11-05T21:00:00Z")],
        "available": [Decimal("2400.25"), utc("2026-11-05T21:00:00Z")],
    }],
}

CARD_EXPECTED = {
    "institution": {"organization": "Cartão Fictício", "id": "FICTICIO-002"},
    "statements": [{
        "kind": "credit_card", "currency": "BRL",
        "account": {"bankId": None, "branchId": None, "accountId": "CARTAO-FICTICIO-001", "accountType": None, "accountKey": None},
        "range": [utc("2026-11-01T00:00:00Z"), utc("2026-12-01T00:00:00Z")],
        "rows": [
            {"type": "DEBIT", "amount": Decimal("-89.90"), "fitId": "FIC-CARTAO-001", "posted": utc("2026-11-04T04:00:00.250Z"), "name": "Livraria fictícia", "memo": "Compra de demonstração"},
            {"type": "CREDIT", "amount": Decimal("10.10"), "fitId": "FIC-CARTAO-002", "posted": utc("2026-11-05T10:00:00Z"), "name": "Crédito fictício", "memo": None},
        ],
        "ledger": [Decimal("-380.80"), utc("2026-11-06T12:00:00Z")],
        "available": [Decimal("500.00"), utc("2026-11-06T12:00:00Z")],
    }],
}


@dataclass(frozen=True)
class Case:
    name: str
    raw: bytes
    expected: dict


def common_cases() -> list[Case]:
    """Variantes de transporte mantêm expectativas escritas à mão."""
    bank = (PROJECT / "examples" / "banco.ofx").read_bytes()
    card = (PROJECT / "examples" / "cartao.ofx").read_bytes()
    cases = [Case("banco-sgml-cp1252", bank, BANK_EXPECTED), Case("cartao-xml-utf8", card, CARD_EXPECTED)]
    for v in (103, 151, 160):
        cases.append(Case(f"banco-versao-{v}", bank.replace(b"VERSION:102", f"VERSION:{v}".encode()), BANK_EXPECTED))
    for v in (200, 201, 202, 203, 210, 211):
        cases.append(Case(f"cartao-versao-{v}", card.replace(b'VERSION="220"', f'VERSION="{v}"'.encode()), CARD_EXPECTED))
    text = bank.decode("cp1252")
    cases.append(Case("banco-utf8", text.replace("ENCODING:USASCII", "ENCODING:UTF-8").replace("CHARSET:1252", "CHARSET:NONE").encode("utf-8"), BANK_EXPECTED))
    cases.append(Case("banco-latin1", text.replace("CHARSET:1252", "CHARSET:ISO-8859-1").encode("latin-1"), BANK_EXPECTED))
    closed = re.sub(r"<([A-Z][A-Z0-9_.]*)>([^<\r\n]+)", lambda m: f"<{m[1]}>{m[2]}</{m[1]}>", text)
    cases.append(Case("banco-folhas-fechadas", closed.encode("cp1252"), BANK_EXPECTED))
    cases.append(Case("banco-ponto-decimal", bank.replace(b"-25,75", b"-25.75"), BANK_EXPECTED))
    cases.append(Case("banco-espacos-nas-bordas", bank.replace(b"<CURDEF>BRL", b"<CURDEF> BRL ").replace(b"<TRNAMT>+1500.25", b"<TRNAMT> +1500.25 "), BANK_EXPECTED))
    empty_expected = deepcopy(BANK_EXPECTED)
    empty_expected["statements"][0]["rows"] = []
    empty = re.sub(rb"<STMTTRN>.*?</STMTTRN>\s*", b"", bank, flags=re.DOTALL)
    cases.append(Case("banco-lista-presente-vazia", empty, empty_expected))
    second = bank[bank.index(b"<STMTTRNRS>"):bank.index(b"</STMTTRNRS>") + len(b"</STMTTRNRS>")]
    second = second.replace(b"CONTA-FICTICIA-001", b"CONTA-FICTICIA-002").replace(b"FIC-RESPOSTA-BANCO-001", b"FIC-RESPOSTA-BANCO-002")
    multi_expected = deepcopy(BANK_EXPECTED)
    second_expected = deepcopy(BANK_EXPECTED["statements"][0])
    second_expected["account"]["accountId"] = "CONTA-FICTICIA-002"
    multi_expected["statements"].append(second_expected)
    cases.append(Case("banco-duas-contas-fitids-iguais", bank.replace(b"</BANKMSGSRSV1>", second + b"\n</BANKMSGSRSV1>"), multi_expected))
    edge_expected = deepcopy(BANK_EXPECTED)
    edge_expected["statements"][0]["rows"][0]["amount"] = Decimal("0.5")
    edge_expected["statements"][0]["rows"][1]["amount"] = Decimal("1")
    cases.append(Case("banco-fracao-sem-inteiro-e-ponto-final", bank.replace(b"+1500.25", b".5").replace(b"-25,75", b"1."), edge_expected))
    day_expected = deepcopy(CARD_EXPECTED)
    day_expected["statements"][0]["rows"][0]["posted"] = utc("2026-11-04T00:00:00Z")
    cases.append(Case("cartao-data-sem-horario", card.replace(b"20261104060000.250[+2:EET]", b"20261104"), day_expected))
    cases.append(Case("cartao-comentario-xml", card.replace(b"<OFX>", b"<OFX><!-- exemplo inteiramente ficticio -->"), CARD_EXPECTED))
    plus_expected = deepcopy(CARD_EXPECTED)
    cases.append(Case("cartao-sinal-positivo", card.replace(b">10.10<", b">+10.10<"), plus_expected))
    return cases


def report_projection(report: dict) -> dict:
    def balance(value):
        return None if value is None else [Decimal(value["amount"]["value"]), utc(value["asOf"]["utc"])]

    result = {"institution": report["institution"], "statements": []}
    for stmt in report["statements"]:
        window = stmt["range"]
        result["statements"].append({
            "kind": stmt["kind"], "currency": stmt["currency"], "account": stmt["account"],
            "range": None if window is None else [utc(window["start"]["utc"]), utc(window["end"]["utc"])],
            "rows": [{"type": row["type"], "amount": Decimal(row["amount"]["value"]), "fitId": row["fitId"], "posted": utc(row["posted"]["utc"]), "name": row["name"], "memo": row["memo"]} for row in stmt["transactions"]],
            "ledger": balance(stmt["ledgerBalance"]), "available": balance(stmt["availableBalance"]),
        })
    return result


def oracle_projection(raw: bytes) -> dict:
    """Use árvore e modelos públicos, sem chamar os conversores do leitor local."""
    from ofxtools.Parser import OFXTree

    tree = OFXTree()
    tree.parse(BytesIO(raw))
    model = tree.convert()
    institution = model.signon.fi
    result = {"institution": None if institution is None else {"organization": institution.org, "id": institution.fid}, "statements": []}

    def balance(value):
        return None if value is None else [value.balamt, value.dtasof]

    for stmt in model.statements:
        acct = stmt.account
        txs = stmt.banktranlist
        result["statements"].append({
            "kind": "bank" if stmt.__class__.__name__ == "STMTRS" else "credit_card",
            "currency": stmt.curdef,
            "account": {out: getattr(acct, attr, None) for out, attr in (("bankId", "bankid"), ("branchId", "branchid"), ("accountId", "acctid"), ("accountType", "accttype"), ("accountKey", "acctkey"))},
            "range": None if txs is None else [txs.dtstart, txs.dtend],
            "rows": [] if txs is None else [{"type": row.trntype, "amount": row.trnamt, "fitId": row.fitid, "posted": row.dtposted, "name": row.name, "memo": row.memo} for row in txs],
            "ledger": balance(stmt.ledgerbal), "available": balance(stmt.availbal),
        })
    # A contagem da árvore inicial deve concordar com a do modelo convertido.
    assert len(tree.findall(".//STMTTRN")) == sum(len(stmt["rows"]) for stmt in result["statements"])
    return result


def fractional_case(token: str) -> bytes:
    card = (PROJECT / "examples" / "cartao.ofx").read_bytes()
    return card.replace(b"20261104060000.250[+2:EET]", f"20261104060000.250[{token}:TEST]".encode("ascii"))


def known_divergences(parse_ofx) -> list[dict]:
    """Expectativas deliberadas: estes casos nunca entram nas concordâncias."""
    from ofxtools.Types import OFXSpecError
    from ofxtools.header import OFXHeaderError

    result = []
    short = fractional_case("5.5")
    ours = report_projection(parse_ofx(short))["statements"][0]["rows"][0]["posted"]
    assert ours == utc("2026-11-04T00:30:00.250Z")
    try:
        oracle_projection(short)
    except OFXSpecError:
        result.append({"case": "offset-5.5", "result": "oracle_rejected", "countedAsMatch": False})
    else:
        raise AssertionError("ofxtools deixou de rejeitar o offset 5.5; revisar a documentação")

    full = fractional_case("5.50")
    ours = report_projection(parse_ofx(full))["statements"][0]["rows"][0]["posted"]
    theirs = oracle_projection(full)["statements"][0]["rows"][0]["posted"]
    assert ours == utc("2026-11-04T00:30:00.250Z")
    assert theirs == utc("2026-11-04T00:10:00.250Z")
    result.append({"case": "offset-5.50", "result": "different_utc", "countedAsMatch": False})

    raw = (PROJECT / "examples" / "cartao.ofx").read_bytes().replace(b'VERSION="220"', b'VERSION="221"')
    assert parse_ofx(raw)["format"]["version"] == "221"
    try:
        oracle_projection(raw)
    except OFXHeaderError:
        result.append({"case": "version-221", "result": "oracle_rejected", "countedAsMatch": False})
    else:
        raise AssertionError("ofxtools deixou de rejeitar VERSION 221; revisar a documentação")
    return result


def main() -> int:
    try:
        installed = version("ofxtools")
    except PackageNotFoundError:
        raise SystemExit("Instale o extra dev do projeto para executar a comparação opcional.")
    if installed != ORACLE_VERSION:
        raise SystemExit(f"A comparação exige ofxtools=={ORACLE_VERSION}.")
    from extrato_ofx import parse_ofx

    matches = []
    for case in common_cases():
        actual = report_projection(parse_ofx(case.raw))
        reference = oracle_projection(case.raw)
        assert actual == case.expected, f"Expectativa manual divergente: {case.name}"
        assert reference == case.expected, f"Oráculo divergente: {case.name}"
        matches.append(case.name)
    print(json.dumps({"oracle": f"ofxtools=={ORACLE_VERSION}", "matchingCases": matches, "matchingCaseCount": len(matches), "knownDivergences": known_divergences(parse_ofx), "scope": "Fixtures fictícias; campos comuns; nenhuma conciliação ou prova geral de conformidade."}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
