"""Interpretação bancária explícita, sem aplicar correções ou reconciliar saldos."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import re

from .model import Limits, Node, OfxError, ParsedDocument
from .scalars import parse_amount, parse_date, sum_amounts


_TRANSACTION_TYPES = frozenset((
    "CREDIT", "DEBIT", "INT", "DIV", "FEE", "SRVCHG", "DEP", "ATM", "POS",
    "XFER", "CHECK", "PAYMENT", "CASH", "DIRECTDEP", "DIRECTDEBIT", "REPEATPMT", "OTHER",
))
_TRANSPORT = frozenset((
    "DTSERVER", "LANGUAGE", "DTPROFUP", "DTACCTUP", "USERKEY", "TSKEYEXPIRE",
    "SESSCOOKIE", "ACCESSKEY", "INTU.BID",
))


class _Extractor:
    def __init__(self, document, limits):
        self.document = document
        self.limits = limits
        self.responses = []
        self.statements = []
        self.uninterpreted = []
        self.ignored = []
        self.diagnostics = []
        self.transaction_count = 0
        self.signon_status = None

    def diagnostic(self, severity, code, path, **extra):
        self.diagnostics.append({"severity": severity, "code": code, "path": path, **extra})

    def unknown(self, node, path):
        # Somente nomes/caminhos: uma extensão pode conter credenciais ou dados privados.
        self.uninterpreted.append({"path": path, "tag": node.tag})
        self.diagnostic("warning", "uninterpreted_field", path)

    def groups(self, node, path, allowed):
        if node.text.strip():
            raise OfxError("invalid_structure", path=path)
        groups = defaultdict(list)
        counts = defaultdict(int)
        for child in node.children:
            child_path = f"{path}/{child.tag}[{counts[child.tag]}]"
            counts[child.tag] += 1
            if child.tag in allowed:
                groups[child.tag].append((child, child_path))
            else:
                self.unknown(child, child_path)
        return groups

    @staticmethod
    def one(groups, tag, path, required=False):
        entries = groups.get(tag, [])
        if len(entries) > 1:
            raise OfxError("duplicate_field", path=f"{path}/{tag}")
        if not entries:
            if required:
                raise OfxError("missing_field", path=f"{path}/{tag}")
            return None
        return entries[0]

    def leaf(self, groups, tag, path, required=False, identifier=False, nonempty=False):
        entry = self.one(groups, tag, path, required)
        if entry is None:
            return None
        node, leaf_path = entry
        if node.children:
            raise OfxError("invalid_structure", path=leaf_path)
        value = node.text.strip()
        if (required or identifier or nonempty) and not value:
            raise OfxError("empty_field", path=leaf_path)
        if identifier and len(value) > 255:
            raise OfxError("identifier_limit", path=leaf_path)
        return value

    def date(self, groups, tag, path, required=False):
        value = self.leaf(groups, tag, path, required, nonempty=True)
        return None if value is None else self.scalar(parse_date, value, f"{path}/{tag}")

    @staticmethod
    def scalar(parser, value, path):
        try:
            return parser(value)
        except OfxError as exc:
            raise OfxError(exc.code, exc.message, path) from exc

    def status(self, entry):
        node, path = entry
        groups = self.groups(node, path, {"CODE", "SEVERITY", "MESSAGE"})
        code = self.leaf(groups, "CODE", path, required=True)
        if not re.fullmatch(r"[0-9]+", code, re.ASCII):
            raise OfxError("invalid_status", path=f"{path}/CODE")
        severity = self.leaf(groups, "SEVERITY", path, required=True)
        if severity not in {"INFO", "WARN", "ERROR"}:
            raise OfxError("invalid_status", path=f"{path}/SEVERITY")
        message = self.leaf(groups, "MESSAGE", path)
        if code.strip("0") or severity != "INFO":
            self.diagnostic("error" if severity == "ERROR" or code.strip("0") else "warning",
                            "provider_status", path)
        return {"code": code, "severity": severity, "message": message}

    def transport(self, groups, tag, path):
        entry = self.one(groups, tag, path)
        if entry is not None:
            if entry[0].children:
                raise OfxError("invalid_structure", path=entry[1])
            self.ignored.append(entry[1])

    def signon(self, entry):
        node, path = entry
        groups = self.groups(node, path, {"SONRS"})
        sonrs = self.one(groups, "SONRS", path, required=True)
        node, path = sonrs
        groups = self.groups(node, path, {"STATUS", "FI"} | _TRANSPORT)
        self.signon_status = self.status(self.one(groups, "STATUS", path, required=True))
        for tag in sorted(_TRANSPORT):
            self.transport(groups, tag, path)
        fi = self.one(groups, "FI", path)
        if fi is None:
            return None
        node, path = fi
        groups = self.groups(node, path, {"ORG", "FID"})
        return {
            "organization": self.leaf(groups, "ORG", path, identifier=True),
            "id": self.leaf(groups, "FID", path, identifier=True),
        }

    def account(self, entry, kind):
        node, path = entry
        tags = {"ACCTID", "ACCTKEY"}
        if kind == "bank":
            tags |= {"BANKID", "BRANCHID", "ACCTTYPE"}
        groups = self.groups(node, path, tags)
        return {
            "bankId": self.leaf(groups, "BANKID", path, required=True, identifier=True) if kind == "bank" else None,
            "branchId": self.leaf(groups, "BRANCHID", path, identifier=True) if kind == "bank" else None,
            "accountId": self.leaf(groups, "ACCTID", path, required=True, identifier=True),
            "accountType": self.leaf(groups, "ACCTTYPE", path, required=True, identifier=True) if kind == "bank" else None,
            "accountKey": self.leaf(groups, "ACCTKEY", path, identifier=True),
        }

    def balance(self, entry):
        if entry is None:
            return None
        node, path = entry
        groups = self.groups(node, path, {"BALAMT", "DTASOF"})
        amount = self.leaf(groups, "BALAMT", path, required=True)
        return {"amount": self.scalar(parse_amount, amount, f"{path}/BALAMT"),
                "asOf": self.date(groups, "DTASOF", path, required=True)}

    def transaction(self, entry, statement_index, index):
        self.transaction_count += 1
        if self.transaction_count > self.limits.max_transactions:
            raise OfxError("transaction_limit")
        node, path = entry
        groups = self.groups(node, path, {
            "TRNTYPE", "DTPOSTED", "TRNAMT", "FITID", "DTUSER", "DTAVAIL", "NAME", "MEMO",
            "CHECKNUM", "REFNUM", "SRVRTID", "SIC", "PAYEEID", "CORRECTFITID", "CORRECTACTION",
        })
        transaction_type = self.leaf(groups, "TRNTYPE", path, required=True, identifier=True)
        if transaction_type not in _TRANSACTION_TYPES:
            self.uninterpreted.append({"path": f"{path}/TRNTYPE[0]", "tag": "TRNTYPE"})
            self.diagnostic("warning", "unknown_transaction_type", f"{path}/TRNTYPE[0]",
                            statementIndex=statement_index, transactionIndex=index)
        target = self.leaf(groups, "CORRECTFITID", path, identifier=True)
        action = self.leaf(groups, "CORRECTACTION", path, nonempty=True)
        if (target is None) != (action is None):
            raise OfxError("incomplete_correction", path=path)
        correction = None
        if target is not None:
            if action not in {"REPLACE", "DELETE"}:
                raise OfxError("invalid_correction", path=f"{path}/CORRECTACTION")
            correction = {"targetFitId": target, "action": action}
            self.diagnostic("info", "correction_declared", path,
                            statementIndex=statement_index, transactionIndex=index)
        amount = self.leaf(groups, "TRNAMT", path, required=True)
        return {
            "index": index,
            "type": transaction_type,
            "posted": self.date(groups, "DTPOSTED", path, required=True),
            "amount": self.scalar(parse_amount, amount, f"{path}/TRNAMT"),
            "fitId": self.leaf(groups, "FITID", path, required=True, identifier=True),
            "name": self.leaf(groups, "NAME", path),
            "memo": self.leaf(groups, "MEMO", path),
            "userDate": self.date(groups, "DTUSER", path),
            "availableDate": self.date(groups, "DTAVAIL", path),
            "checkNumber": self.leaf(groups, "CHECKNUM", path, identifier=True),
            "referenceNumber": self.leaf(groups, "REFNUM", path, identifier=True),
            "serverId": self.leaf(groups, "SRVRTID", path, identifier=True),
            "sic": self.leaf(groups, "SIC", path, identifier=True),
            "payeeId": self.leaf(groups, "PAYEEID", path, identifier=True),
            "correction": correction,
        }

    def statement(self, entry, kind, response_index):
        if len(self.statements) >= self.limits.max_statements:
            raise OfxError("statement_limit")
        index = len(self.statements)
        node, path = entry
        account_tag = "BANKACCTFROM" if kind == "bank" else "CCACCTFROM"
        groups = self.groups(node, path, {
            "CURDEF", account_tag, "LEDGERBAL", "AVAILBAL", "MKTGINFO", "BANKTRANLIST",
        })
        currency = self.leaf(groups, "CURDEF", path, required=True)
        if not re.fullmatch(r"[A-Z]{3}", currency, re.ASCII):
            raise OfxError("invalid_currency", path=f"{path}/CURDEF")
        account = self.account(self.one(groups, account_tag, path, required=True), kind)
        ledger = self.balance(self.one(groups, "LEDGERBAL", path, required=True))
        available = self.balance(self.one(groups, "AVAILBAL", path))
        marketing = self.leaf(groups, "MKTGINFO", path)
        transactions = []
        bank_list = self.one(groups, "BANKTRANLIST", path)
        date_range = None
        if bank_list is None:
            self.diagnostic("warning", "transactions_not_provided", path, statementIndex=index)
        else:
            list_node, list_path = bank_list
            list_groups = self.groups(list_node, list_path, {"DTSTART", "DTEND", "STMTTRN"})
            start = self.date(list_groups, "DTSTART", list_path, required=True)
            end = self.date(list_groups, "DTEND", list_path, required=True)
            # Comparar instantes, não representações ISO com precisões diferentes.
            if datetime.fromisoformat(start["utc"]) > datetime.fromisoformat(end["utc"]):
                raise OfxError("invalid_range", path=list_path)
            date_range = {"start": start, "end": end, "endExclusive": True}
            for transaction_entry in list_groups.get("STMTTRN", []):
                transactions.append(self.transaction(transaction_entry, index, len(transactions)))
        self.statements.append({
            "index": index, "responseIndex": response_index, "kind": kind, "currency": currency,
            "account": account, "transactionsProvided": bank_list is not None,
            "range": date_range, "ledgerBalance": ledger, "availableBalance": available,
            "marketingInfo": marketing, "transactions": transactions,
            "totals": {"reportedCount": len(transactions),
                       "reportedAmountSum": sum_amounts(item["amount"] for item in transactions)},
        })
        return index

    def message_set(self, entry, kind):
        node, path = entry
        response_tag = "STMTTRNRS" if kind == "bank" else "CCSTMTTRNRS"
        statement_tag = "STMTRS" if kind == "bank" else "CCSTMTRS"
        groups = self.groups(node, path, {response_tag})
        for node, response_path in groups.get(response_tag, []):
            response_groups = self.groups(node, response_path, {"TRNUID", "STATUS", "CLTCOOKIE", statement_tag})
            uid = self.leaf(response_groups, "TRNUID", response_path, required=True, identifier=True)
            status = self.status(self.one(response_groups, "STATUS", response_path, required=True))
            self.transport(response_groups, "CLTCOOKIE", response_path)
            statement = self.one(response_groups, statement_tag, response_path,
                                 required=not status["code"].strip("0"))
            response_index = len(self.responses)
            statement_index = None if statement is None else self.statement(statement, kind, response_index)
            self.responses.append({"index": response_index, "kind": kind,
                                   "transactionId": uid, "status": status,
                                   "statementIndex": statement_index})

    def duplicates(self):
        groups = defaultdict(list)
        for statement in self.statements:
            account = statement["account"]
            scope = (statement["kind"], account["bankId"], account["branchId"],
                     account["accountId"], account["accountType"])
            for transaction in statement["transactions"]:
                groups[(scope, transaction["fitId"])].append((statement["index"], statement["currency"], transaction))
        for records in groups.values():
            if len(records) < 2:
                continue
            locations = [{"statement": index, "transaction": transaction["index"]}
                         for index, _, transaction in records]
            self.diagnostic("warning", "duplicate_fitid", "/OFX", records=locations)
            baseline = (records[0][1], self.payload(records[0][2]))
            if any((currency, self.payload(record)) != baseline for _, currency, record in records[1:]):
                self.diagnostic("error", "conflicting_fitid", "/OFX", records=locations)

    @staticmethod
    def payload(transaction):
        payload = {key: value for key, value in transaction.items() if key not in {"index", "fitId"}}
        payload["amount"] = transaction["amount"]["value"]
        for key in ("posted", "userDate", "availableDate"):
            value = transaction[key]
            payload[key] = None if value is None else datetime.fromisoformat(value["utc"])
        return payload

    def run(self):
        root = self.document.root
        if root.tag != "OFX":
            raise OfxError("invalid_root")
        path = "/OFX"
        groups = self.groups(root, path, {"SIGNONMSGSRSV1", "BANKMSGSRSV1", "CREDITCARDMSGSRSV1"})
        signon = self.one(groups, "SIGNONMSGSRSV1", path)
        institution = None if signon is None else self.signon(signon)
        # Ordem de respostas acompanha a ordem dos conjuntos no documento.
        seen = set()
        for node in root.children:
            kind = {"BANKMSGSRSV1": "bank", "CREDITCARDMSGSRSV1": "credit_card"}.get(node.tag)
            if kind is not None and node.tag not in seen:
                self.message_set(self.one(groups, node.tag, path), kind)
                seen.add(node.tag)
        if not self.statements:
            self.diagnostic("warning", "no_supported_statements", path)
        self.duplicates()
        incomplete = bool(self.uninterpreted) or not self.statements
        issues = any(diagnostic["severity"] in {"warning", "error"} for diagnostic in self.diagnostics)
        return {
            "schemaVersion": 1,
            "status": "incomplete" if incomplete else "issues" if issues else "ok",
            "format": asdict(self.document.header),
            "institution": institution,
            "signonStatus": self.signon_status,
            "responses": self.responses,
            "statements": self.statements,
            "coverage": {"status": "incomplete" if incomplete else "complete",
                         "uninterpreted": self.uninterpreted, "ignoredTransportPaths": self.ignored},
            "diagnostics": self.diagnostics,
            "stats": {"nodes": self.document.stats.nodes, "maxDepth": self.document.stats.max_depth,
                      "textCharacters": self.document.stats.text_characters,
                      "responseCount": len(self.responses), "statementCount": len(self.statements),
                      "transactionCount": self.transaction_count},
            "limits": asdict(self.limits),
        }


def extract_report(document: ParsedDocument, *, limits: Limits = Limits()) -> dict:
    """Interpreta somente o perfil declarado, mantendo todas as linhas reportadas."""
    if not isinstance(document, ParsedDocument) or not isinstance(limits, Limits):
        raise OfxError("invalid_input")
    return _Extractor(document, limits).run()
