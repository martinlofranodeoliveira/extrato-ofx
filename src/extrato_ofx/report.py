"""Exportações determinísticas com limite de bytes UTF-8."""
import csv
from io import StringIO
import json
import re
from .model import Limits, OfxError


class _Output:
    def __init__(self, limits):
        if not isinstance(limits, Limits):
            raise OfxError("invalid_limits")
        self.limit, self.size, self.parts = limits.max_output_bytes, 0, []

    def add(self, part):
        try:
            size = len(part.encode("utf-8"))
        except (UnicodeError, AttributeError):
            raise OfxError("invalid_report") from None
        if self.size + size > self.limit:
            raise OfxError("output_size")
        self.size += size
        self.parts.append(part)

    def finish(self):
        return "".join(self.parts)


def _check(report):
    if (type(report) is not dict or type(report.get("schemaVersion")) is not int or report.get("schemaVersion") != 1
            or type(report.get("status")) is not str or report.get("status") not in {"ok", "issues", "incomplete"}
            or type(report.get("coverage")) is not dict
            or type(report["coverage"].get("status")) is not str or report["coverage"].get("status") not in {"complete", "incomplete"}
            or any(type(report.get(key)) is not list for key in ("statements", "responses", "diagnostics"))):
        raise OfxError("invalid_report")
    # Explicitly avoid floats, arbitrary objects, cycles and pathological reports
    # supplied by API callers. No original financial values are logged here.
    active, visited = set(), 0
    def walk(value, depth):
        nonlocal visited
        visited += 1
        # At this count even the smallest JSON cannot fit the absolute 32 MiB
        # export ceiling. Avoid a lower hidden cap on legitimate large reports.
        if depth > 64 or visited > 32 * 1024 * 1024:
            raise OfxError("invalid_report")
        if value is None or type(value) in (str, int, bool):
            return
        if type(value) not in (dict, list):
            raise OfxError("invalid_report")
        identity = id(value)
        if identity in active:
            raise OfxError("invalid_report")
        active.add(identity)
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise OfxError("invalid_report")
                walk(item, depth + 1)
        else:
            for item in value:
                walk(item, depth + 1)
        active.remove(identity)
    walk(report, 0)


def to_json(report: dict, *, limits: Limits = Limits()) -> str:
    _check(report)
    output = _Output(limits)
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, indent=2)
        for part in encoder.iterencode(report):
            output.add(part)
        output.add("\n")
    except OfxError:
        raise
    except (TypeError, ValueError, RecursionError):
        raise OfxError("invalid_report") from None
    return output.finish()


def _md(value):
    # Escape every punctuation mark that can become Markdown/HTML syntax.
    # Source newlines are represented as text, never new rows or HTML.
    text = str(value) if value is not None else "—"
    text = text.replace("\r\n", " ⏎ ").replace("\r", " ⏎ ").replace("\n", " ⏎ ")
    text = "".join(char if ord(char) >= 32 and ord(char) != 127 else " " for char in text)
    return re.sub(r"([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\\\1", text)


def to_markdown(report: dict, *, limits: Limits = Limits()) -> str:
    _check(report)
    out = _Output(limits)
    try:
        out.add("# Extrato OFX\n\n")
        out.add("Resumo dos registros declarados no arquivo. Nenhum saldo inicial foi deduzido; correções e duplicatas permanecem no resultado.\n\n")
        out.add(f"Estado: **{_md(report['status'])}** · Cobertura do perfil: **{_md(report['coverage']['status'])}**\n\n")
        fmt = report["format"]
        out.add(f"Formato: {_md(fmt['dialect'])} / {_md(fmt['version'])} · Codificação: {_md(fmt['encoding'])}\n\n")
        institution = report.get("institution")
        if institution:
            out.add(f"Instituição: {_md(institution.get('organization'))} · ID: {_md(institution.get('id'))}\n\n")
        signon = report.get("signonStatus")
        if signon is not None:
            out.add(f"Status de sessão: {_md(signon['code'])} / {_md(signon['severity'])} · {_md(signon.get('message'))}\n\n")
        for response in report["responses"]:
            status = response["status"]
            out.add(f"Resposta {_md(response['index'])}: {_md(status['code'])} / {_md(status['severity'])} · {_md(status.get('message'))}\n\n")
        for statement in report["statements"]:
            account = statement["account"]
            out.add(f"## Extrato {statement['index'] + 1} — {_md(statement['kind'])}\n\n")
            out.add(f"Conta: {_md(account['accountId'])} · Banco: {_md(account.get('bankId'))} · Agência: {_md(account.get('branchId'))} · Tipo: {_md(account.get('accountType'))} · Moeda: {_md(statement['currency'])}\n\n")
            if statement["range"] is not None:
                interval = statement["range"]
                out.add(f"Janela solicitada: {_md(interval['start']['iso'])} até {_md(interval['end']['iso'])}, fim exclusivo. Ela não comprova o histórico completo da conta.\n\n")
            else:
                out.add("Lista de transações não fornecida; ausência de lista não significa ausência de atividade.\n\n")
            for key, title in (("ledgerBalance", "Saldo contábil"), ("availableBalance", "Saldo disponível")):
                balance = statement.get(key)
                if balance:
                    out.add(f"{title}: {_md(balance['amount']['value'])} em {_md(balance['asOf']['iso'])}.\n\n")
            out.add(f"Linhas declaradas: {_md(statement['totals']['reportedCount'])} · Soma das linhas: {_md(statement['totals']['reportedAmountSum'])}. Esta soma inclui correções e duplicatas; não é conciliação de saldo.\n\n")
            out.add("| Data declarada | Tipo | Valor | FITID | Nome / memo | Correção |\n| --- | --- | --- | --- | --- | --- |\n")
            for row in statement["transactions"]:
                correction = row["correction"]
                description = " / ".join(x for x in (row.get("name"), row.get("memo")) if x is not None)
                corr = "—" if correction is None else correction["action"] + " " + correction["targetFitId"]
                out.add("| " + " | ".join(_md(x) for x in (row["posted"]["raw"], row["type"], row["amount"]["value"], row["fitId"], description, corr)) + " |\n")
            out.add("\n")
        out.add("## Diagnósticos\n\n")
        if not report["diagnostics"]:
            out.add("Nenhum diagnóstico neste perfil.\n\n")
        for item in report["diagnostics"]:
            out.add(f"- {_md(item['severity'])}: {_md(item['code'])} em {_md(item['path'])}\n")
        out.add("\nO JSON contém os campos opcionais e metadados completos interpretados por este leitor. Este relatório contém dados financeiros; trate-o como privado.\n")
    except (KeyError, TypeError, IndexError, AttributeError):
        raise OfxError("invalid_report") from None
    return out.finish()


_COLUMNS = (
    "report_status", "coverage", "statement", "kind", "currency", "bank_id", "branch_id", "account_id", "account_type",
    "range_start", "range_end_exclusive", "ledger_amount", "ledger_as_of", "transaction", "type", "posted_raw", "posted_iso", "posted_utc",
    "amount", "amount_raw", "fit_id", "name", "memo", "user_date", "available_date", "check_number", "reference_number", "server_id", "sic", "payee_id", "correction_action", "correction_target_fit_id",
)
_NUMERIC_COLUMNS = {"statement", "transaction", "amount", "ledger_amount"}


def _cell(value, *, safe):
    if value is None:
        return ""
    text = str(value)
    if safe and text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def to_csv(report: dict, *, limits: Limits = Limits(), allow_incomplete: bool = False, spreadsheet_safe: bool = True) -> str:
    _check(report)
    if type(allow_incomplete) is not bool or type(spreadsheet_safe) is not bool:
        raise OfxError("invalid_report")
    if report["coverage"]["status"] == "incomplete" and not allow_incomplete:
        raise OfxError("incomplete_csv")
    out = _Output(limits)
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    def add(values):
        buffer.seek(0)
        buffer.truncate()
        writer.writerow(values)
        out.add(buffer.getvalue())
    add(_COLUMNS)
    try:
        for statement in report["statements"]:
            account, interval, balance = statement["account"], statement["range"], statement["ledgerBalance"]
            for row in statement["transactions"]:
                correction = row["correction"] or {}
                values = (
                    report["status"], report["coverage"]["status"], statement["index"], statement["kind"], statement["currency"],
                    account["bankId"], account["branchId"], account["accountId"], account["accountType"],
                    interval["start"]["iso"] if interval else None, interval["end"]["iso"] if interval else None,
                    balance["amount"]["value"], balance["asOf"]["iso"], row["index"], row["type"], row["posted"]["raw"], row["posted"]["iso"], row["posted"]["utc"],
                    row["amount"]["value"], row["amount"]["raw"], row["fitId"], row["name"], row["memo"],
                    row["userDate"]["iso"] if row["userDate"] else None, row["availableDate"]["iso"] if row["availableDate"] else None,
                    row["checkNumber"], row["referenceNumber"], row["serverId"], row["sic"], row["payeeId"], correction.get("action"), correction.get("targetFitId"),
                )
                cells = []
                for col, value in zip(_COLUMNS, values):
                    if col in {"statement", "transaction"}:
                        if type(value) is not int or value < 0:
                            raise OfxError("invalid_report")
                    elif col in _NUMERIC_COLUMNS:
                        if type(value) is not str or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
                            raise OfxError("invalid_report")
                    cells.append(_cell(value, safe=spreadsheet_safe and col not in _NUMERIC_COLUMNS))
                add(cells)
    except (KeyError, TypeError, IndexError, AttributeError, csv.Error):
        raise OfxError("invalid_report") from None
    return out.finish()
