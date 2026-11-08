"""Casos semânticos sintéticos; a construção de árvores não usa o parser."""
from dataclasses import replace
import json
import unittest

from extrato_ofx.extract import extract_report
from extrato_ofx.model import Header, Limits, Node, OfxError, ParsedDocument, ParseStats


def leaf(tag, text):
    return Node(tag, text)


def group(tag, *children):
    return Node(tag, children=tuple(children))


def status(code="0", severity="INFO", *extra):
    return group("STATUS", leaf("CODE", code), leaf("SEVERITY", severity), *extra)


def transaction(fitid="FICTICIO-001", amount="-10.25", date="20261018153000[-3:BRT]", *extra):
    return group("STMTTRN", leaf("TRNTYPE", "DEBIT"), leaf("DTPOSTED", date),
                 leaf("TRNAMT", amount), leaf("FITID", fitid), *extra)


def statement(*transactions, kind="bank", account="000001", listed=True, extra=(),
              start="20261018", end="20261019", currency="BRL"):
    account_node = (group("BANKACCTFROM", leaf("BANKID", "999"), leaf("ACCTID", account),
                          leaf("ACCTTYPE", "CHECKING")) if kind == "bank" else
                    group("CCACCTFROM", leaf("ACCTID", account)))
    fields = [leaf("CURDEF", currency), account_node,
              group("LEDGERBAL", leaf("BALAMT", "123.456"), leaf("DTASOF", "20261019"))]
    if listed:
        fields.append(group("BANKTRANLIST", leaf("DTSTART", start), leaf("DTEND", end), *transactions))
    return group("STMTRS" if kind == "bank" else "CCSTMTRS", *fields, *extra)


def response(stmt=None, *, kind="bank", uid="REQ-FICTICIA-001", code="0", severity="INFO", extra=()):
    return group("STMTTRNRS" if kind == "bank" else "CCSTMTTRNRS",
                 leaf("TRNUID", uid), status(code, severity), *((stmt,) if stmt is not None else ()), *extra)


def document(*responses, signon=None, root_extra=()):
    bank = tuple(item for item in responses if item.tag == "STMTTRNRS")
    card = tuple(item for item in responses if item.tag == "CCSTMTTRNRS")
    root = group("OFX", *((signon,) if signon else ()),
                 *((group("BANKMSGSRSV1", *bank),) if bank else ()),
                 *((group("CREDITCARDMSGSRSV1", *card),) if card else ()), *root_extra)
    return ParsedDocument(Header("xml", "220", "utf-8"), root, ParseStats(100, 8, 500))


def replace_child(node, tag, replacement):
    return replace(node, children=tuple(replacement if child.tag == tag else child for child in node.children))


class ExtractTests(unittest.TestCase):
    def report(self, *args, **kwargs):
        return extract_report(document(*args, **kwargs))

    def assertCode(self, code, callback):
        with self.assertRaises(OfxError) as captured:
            callback()
        self.assertEqual(captured.exception.code, code)

    def test_bank_values_and_account_leading_zeros(self):
        report = self.report(response(statement(transaction())))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["coverage"]["status"], "complete")
        stmt = report["statements"][0]
        self.assertEqual(stmt["account"], {"bankId": "999", "branchId": None,
                                          "accountId": "000001", "accountType": "CHECKING", "accountKey": None})
        self.assertEqual(stmt["ledgerBalance"]["amount"]["value"], "123.456")
        self.assertEqual(stmt["totals"], {"reportedCount": 1, "reportedAmountSum": "-10.25"})
        self.assertEqual(stmt["transactions"][0]["posted"]["utc"], "2026-10-18T18:30:00Z")
        self.assertTrue(stmt["range"]["endExclusive"])
        self.assertNotIn("openingBalance", stmt)
        self.assertEqual(report["responses"][0]["statementIndex"], 0)
        self.assertIsNone(report["signonStatus"])

    def test_card_and_bank_responses(self):
        report = self.report(response(statement()),
                             response(statement(transaction(amount="4"), kind="credit_card"), kind="credit_card"))
        self.assertEqual([item["kind"] for item in report["statements"]], ["bank", "credit_card"])
        self.assertIsNone(report["statements"][1]["account"]["bankId"])
        self.assertEqual(report["stats"]["statementCount"], 2)
        self.assertEqual(report["stats"]["transactionCount"], 1)

    def test_input_is_unchanged(self):
        doc = document(response(statement(transaction())))
        before = repr(doc)
        extract_report(doc)
        self.assertEqual(repr(doc), before)

    def test_empty_and_absent_lists_are_distinct(self):
        empty = self.report(response(statement()))
        absent = self.report(response(statement(listed=False)))
        self.assertTrue(empty["statements"][0]["transactionsProvided"])
        self.assertEqual(empty["status"], "ok")
        self.assertFalse(absent["statements"][0]["transactionsProvided"])
        self.assertIsNone(absent["statements"][0]["range"])
        self.assertEqual(absent["status"], "issues")
        self.assertEqual(absent["diagnostics"][0]["code"], "transactions_not_provided")
        self.assertEqual(absent["coverage"]["status"], "complete")

    def test_date_search_window_does_not_filter_transactions(self):
        report = self.report(response(statement(transaction(date="20200101"))))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["stats"]["transactionCount"], 1)

    def test_range_compares_instants(self):
        self.assertCode("invalid_range", lambda: self.report(response(statement(
            start="20261018010000[-3]", end="20261018030000[0]"))))
        valid = self.report(response(statement(start="20261018010000[-3]", end="20261018050000[1]")))
        self.assertEqual(valid["status"], "ok")

    def test_exact_sum_all_rows_even_corrections(self):
        trn = transaction("CORRIGIDA", "0.000000000000000000000001", "20261018",
                          leaf("CORRECTFITID", "ALVO-AUSENTE"), leaf("CORRECTACTION", "DELETE"))
        report = self.report(response(statement(transaction(amount="99999999999999999999999"), trn)))
        self.assertEqual(report["statements"][0]["totals"]["reportedAmountSum"],
                         "99999999999999999999999.000000000000000000000001")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["diagnostics"][0]["code"], "correction_declared")

    def test_correction_pair_required_and_action_checked(self):
        for fields, code in [((leaf("CORRECTFITID", "ALVO"),), "incomplete_correction"),
                             ((leaf("CORRECTACTION", "DELETE"),), "incomplete_correction"),
                             ((leaf("CORRECTFITID", "ALVO"), leaf("CORRECTACTION", "MERGE")), "invalid_correction")]:
            with self.subTest(code=code):
                self.assertCode(code, lambda: self.report(response(statement(transaction("X", "1", "20261018", *fields)))))

    def test_duplicate_group_across_statements_keeps_every_row(self):
        report = self.report(response(statement(transaction())), response(statement(transaction()), uid="REQ-2"))
        duplicates = [d for d in report["diagnostics"] if d["code"] == "duplicate_fitid"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0]["records"], [{"statement": 0, "transaction": 0}, {"statement": 1, "transaction": 0}])
        self.assertEqual(report["stats"]["transactionCount"], 2)
        self.assertEqual(report["status"], "issues")
        self.assertNotIn("conflicting_fitid", [d["code"] for d in report["diagnostics"]])

    def test_duplicate_comparison_normalizes_amount_and_time(self):
        first = transaction("X", "+1,000", "20261018153000[-3:BRT]")
        second = transaction("X", "1.0", "20261018183000.000[0:UTC]")
        report = self.report(response(statement(first, second)))
        self.assertEqual([d["code"] for d in report["diagnostics"]], ["duplicate_fitid"])

    def test_conflicting_duplicate_is_reported_without_deduplication(self):
        report = self.report(response(statement(transaction("X", "1"), transaction("X", "2"), transaction("X", "2"))))
        self.assertEqual([d["code"] for d in report["diagnostics"]], ["duplicate_fitid", "conflicting_fitid"])
        self.assertEqual(report["statements"][0]["totals"]["reportedAmountSum"], "5")

    def test_fitid_is_scoped_by_account_and_case_sensitive(self):
        report = self.report(response(statement(transaction("X"), transaction("x"))),
                             response(statement(transaction("X"), account="000002"), uid="REQ-2"))
        self.assertEqual(report["diagnostics"], [])

    def test_currency_difference_is_a_conflicting_duplicate(self):
        report = self.report(response(statement(transaction("X", "1"), currency="BRL")),
                             response(statement(transaction("X", "1"), currency="USD"), uid="REQ-2"))
        self.assertEqual([d["code"] for d in report["diagnostics"]], ["duplicate_fitid", "conflicting_fitid"])

    def test_account_key_is_not_duplicate_scope(self):
        first = statement(transaction(), extra=())
        second = replace_child(first, "BANKACCTFROM", group("BANKACCTFROM", leaf("BANKID", "999"),
                               leaf("ACCTID", "000001"), leaf("ACCTTYPE", "CHECKING"), leaf("ACCTKEY", "MUDOU")))
        report = self.report(response(first), response(second, uid="REQ-2"))
        self.assertEqual(report["diagnostics"][0]["code"], "duplicate_fitid")

    def test_provider_error_can_omit_statement(self):
        report = self.report(response(code="2000", severity="ERROR"))
        self.assertIsNone(report["responses"][0]["statementIndex"])
        self.assertEqual(report["responses"][0]["status"]["code"], "2000")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual([d["code"] for d in report["diagnostics"]], ["provider_status", "no_supported_statements"])

    def test_success_response_requires_statement(self):
        self.assertCode("missing_field", lambda: self.report(response()))

    def test_warning_provider_status_and_zero_padded_code(self):
        report = self.report(response(statement(), code="000", severity="WARN"))
        self.assertEqual(report["status"], "issues")
        self.assertEqual(report["responses"][0]["status"]["code"], "000")

    def test_status_code_and_severity_are_validated(self):
        for code, severity in [("+1", "ERROR"), ("1.0", "ERROR"), ("１２", "ERROR"), ("0", "info")]:
            self.assertCode("invalid_status", lambda: self.report(response(statement(), code=code, severity=severity)))

    def test_institution_and_transport_secrets(self):
        signon = group("SIGNONMSGSRSV1", group("SONRS", status(),
                       group("FI", leaf("ORG", "INSTITUICAO FICTICIA"), leaf("FID", "000999")),
                       leaf("USERKEY", "SEGREDO-NAO-EXPORTAR"), leaf("SESSCOOKIE", "COOKIE-NAO-EXPORTAR"),
                       leaf("DTSERVER", "20261018")))
        report = self.report(response(statement(), extra=(leaf("CLTCOOKIE", "COOKIE-CLIENTE-PRIVADO"),)), signon=signon)
        self.assertEqual(report["institution"], {"organization": "INSTITUICAO FICTICIA", "id": "000999"})
        serialized = json.dumps(report)
        for secret in ["SEGREDO-NAO-EXPORTAR", "COOKIE-NAO-EXPORTAR", "COOKIE-CLIENTE-PRIVADO"]:
            self.assertNotIn(secret, serialized)
        self.assertEqual(len(report["coverage"]["ignoredTransportPaths"]), 4)
        self.assertEqual(report["signonStatus"], {"code": "0", "severity": "INFO", "message": None})

    def test_signon_status_is_preserved_including_message(self):
        signon = group("SIGNONMSGSRSV1", group("SONRS", status("2000", "ERROR", leaf("MESSAGE", "Erro fictício do provedor"))))
        report = self.report(response(statement()), signon=signon)
        self.assertEqual(report["signonStatus"], {"code": "2000", "severity": "ERROR", "message": "Erro fictício do provedor"})
        self.assertEqual(report["diagnostics"][0]["code"], "provider_status")
        self.assertEqual(report["status"], "issues")

    def test_unknown_fields_are_incomplete_without_exporting_values(self):
        extension = group("EXTENSAO", leaf("SUBCAMPO", "SEGREDO-DESCONHECIDO"))
        report = self.report(response(statement(transaction("X", "1", "20261018", extension))),
                             root_extra=(leaf("OUTRO", "SEGREDO-RAIZ"),))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual([entry["tag"] for entry in report["coverage"]["uninterpreted"]], ["OUTRO", "EXTENSAO"])
        self.assertNotIn("SEGREDO-", json.dumps(report))

    def test_unknown_transaction_type_preserved_but_not_claimed_complete(self):
        trn = replace_child(transaction(), "TRNTYPE", leaf("TRNTYPE", "EXTENSAO-BANCO"))
        report = self.report(response(statement(trn)))
        self.assertEqual(report["statements"][0]["transactions"][0]["type"], "EXTENSAO-BANCO")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["diagnostics"][0]["code"], "unknown_transaction_type")

    def test_duplicate_singleton_and_invalid_structure_fail(self):
        stmt = statement(transaction("X", "1", "20261018", leaf("FITID", "Y")))
        self.assertCode("duplicate_field", lambda: self.report(response(stmt)))
        stmt = statement(extra=(leaf("CURDEF", "USD"),))
        self.assertCode("duplicate_field", lambda: self.report(response(stmt)))
        bad = replace_child(statement(), "CURDEF", group("CURDEF", leaf("CHILD", "BRL")))
        self.assertCode("invalid_structure", lambda: self.report(response(bad)))

    def test_missing_required_fields_and_empty_optional_ids_fail(self):
        for tag in ["CURDEF", "BANKACCTFROM", "LEDGERBAL"]:
            stmt = statement()
            stmt = replace(stmt, children=tuple(c for c in stmt.children if c.tag != tag))
            self.assertCode("missing_field", lambda: self.report(response(stmt)))
        self.assertCode("empty_field", lambda: self.report(response(statement(transaction("X", "1", "20261018", leaf("REFNUM", "  "))))))
        self.assertCode("identifier_limit", lambda: self.report(response(statement(transaction("X" * 256)))))

    def test_currency_syntax_is_checked_without_claiming_currency_registry(self):
        self.assertEqual(self.report(response(statement(currency="ZZZ")))["status"], "ok")
        self.assertCode("invalid_currency", lambda: self.report(response(statement(currency="brl"))))

    def test_available_balance_and_optional_transaction_fields(self):
        trn = transaction("F", "1", "20261018", leaf("DTUSER", "20261017"), leaf("DTAVAIL", "20261020"),
                          leaf("NAME", "  Loja fictícia  "), leaf("MEMO", "linha 1\nlinha 2"),
                          leaf("CHECKNUM", "0002"), leaf("REFNUM", "R"), leaf("SRVRTID", "S"),
                          leaf("SIC", "0001"), leaf("PAYEEID", "P"))
        available = group("AVAILBAL", leaf("BALAMT", "100,75"), leaf("DTASOF", "20261020"))
        report = self.report(response(statement(trn, extra=(available, leaf("MKTGINFO", "Informação fictícia")))))
        stmt = report["statements"][0]
        self.assertEqual(stmt["availableBalance"]["amount"]["value"], "100.75")
        self.assertEqual(stmt["marketingInfo"], "Informação fictícia")
        self.assertEqual(stmt["transactions"][0]["name"], "Loja fictícia")
        self.assertEqual(stmt["transactions"][0]["checkNumber"], "0002")
        self.assertEqual(stmt["transactions"][0]["memo"], "linha 1\nlinha 2")

    def test_limits_are_global_across_accounts(self):
        doc = document(response(statement(transaction())), response(statement(transaction(), account="2")))
        self.assertCode("statement_limit", lambda: extract_report(doc, limits=Limits(max_statements=1)))
        self.assertCode("transaction_limit", lambda: extract_report(doc, limits=Limits(max_transactions=1)))

    def test_response_order_matches_root_order(self):
        doc = document(response(statement()), response(statement(kind="credit_card"), kind="credit_card"))
        doc = replace(doc, root=replace(doc.root, children=tuple(reversed(doc.root.children))))
        report = extract_report(doc)
        self.assertEqual([r["kind"] for r in report["responses"]], ["credit_card", "bank"])

    def test_transport_only_and_unsupported_root_never_claim_zero_activity(self):
        signon = group("SIGNONMSGSRSV1", group("SONRS", status()))
        for report in [self.report(signon=signon), self.report(root_extra=(group("INVSTMTMSGSRSV1"),))]:
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["statements"], [])

    def test_duplicate_message_set_fails(self):
        extra = group("BANKMSGSRSV1", response(statement()))
        self.assertCode("duplicate_field", lambda: self.report(response(statement()), root_extra=(extra,)))


if __name__ == "__main__":
    unittest.main()
