"""Fixtures de transporte inteiramente fictícias, sem contas reais."""
from dataclasses import replace
import unittest

from extrato_ofx.model import Limits, OfxError
from extrato_ofx.parser import parse_document


def sgml(body="<OFX><NAME>Exemplo</OFX>", *, encoding="UTF-8", charset="NONE", version="102"):
    header = (
        f"OFXHEADER:100\nDATA:OFXSGML\nVERSION:{version}\nSECURITY:NONE\n"
        f"ENCODING:{encoding}\nCHARSET:{charset}\nCOMPRESSION:NONE\n"
        "OLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
    )
    codec = "cp1252" if charset == "1252" else "latin-1" if charset in {"ISO-8859-1", "8859-1"} else "ascii" if encoding == "USASCII" else "utf-8"
    return (header + body).encode(codec)


def xml(body="<OFX><NAME>Exemplo</NAME></OFX>", *, version="220", encoding="UTF-8"):
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>\n'
        f'<?OFX OFXHEADER="200" VERSION="{version}" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>\n'
        + body
    ).encode("utf-8" if encoding == "UTF-8" else "ascii")


class ParserTests(unittest.TestCase):
    def assert_code(self, code, raw, **kwargs):
        with self.assertRaises(OfxError) as caught:
            parse_document(raw, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_sgml_optional_leaf_close_and_case(self):
        result = parse_document(sgml("<ofx><name> A &amp; B <memo>nota</memo></ofx>"))
        self.assertEqual(result.root.tag, "OFX")
        self.assertEqual([(n.tag, n.text) for n in result.root.children], [("NAME", " A & B "), ("MEMO", "nota")])
        self.assertEqual(result.header.encoding, "utf-8")
        self.assertEqual(result.stats.nodes, 3)
        self.assertEqual(result.stats.max_depth, 2)

    def test_xml_tree_matches_sgml(self):
        body = "<OFX><BANKMSGSRSV1><STMTTRNRS><TRNUID>demo</TRNUID><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS></STMTTRNRS></BANKMSGSRSV1></OFX>"
        self.assertEqual(parse_document(xml(body)).root, parse_document(sgml(body)).root)

    def test_xml_utf8_and_bom(self):
        result = parse_document(b"\xef\xbb\xbf" + xml("<OFX><NAME>Óleo e café 🛒</NAME></OFX>"))
        self.assertEqual(result.root.children[0].text, "Óleo e café 🛒")

    def test_xml_default_encoding_and_single_quotes(self):
        raw = xml().replace(b' encoding="UTF-8"', b"").replace(b'"', b"'")
        self.assertEqual(parse_document(raw).header.encoding, "utf-8")

    def test_ascii(self):
        self.assertEqual(parse_document(xml(encoding="US-ASCII")).header.encoding, "ascii")
        self.assertEqual(parse_document(sgml(encoding="USASCII")).header.encoding, "ascii")

    def test_cp1252(self):
        result = parse_document(sgml("<OFX><NAME>Compra – café</OFX>", encoding="USASCII", charset="1252"))
        self.assertEqual(result.root.children[0].text, "Compra – café")
        self.assertEqual(result.header.encoding, "cp1252")

    def test_latin1_aliases(self):
        for charset in ("ISO-8859-1", "8859-1"):
            with self.subTest(charset=charset):
                result = parse_document(sgml("<OFX><NAME>café</OFX>", encoding="USASCII", charset=charset))
                self.assertEqual(result.root.children[0].text, "café")
                self.assertEqual(result.header.encoding, "latin-1")

    def test_supported_versions(self):
        for version in ("102", "103", "151", "160"):
            self.assertEqual(parse_document(sgml(version=version)).header.version, version)
        for version in ("200", "201", "202", "203", "210", "211", "220", "221"):
            self.assertEqual(parse_document(xml(version=version)).header.version, version)

    def test_numeric_and_predefined_entities(self):
        expected = 'A & < > " \' 😀'
        for raw in (sgml("<OFX><NAME>&#65; &amp; &lt; &gt; &quot; &apos; &#x1F600;</OFX>"), xml("<OFX><NAME>&#65; &amp; &lt; &gt; &quot; &apos; &#x1F600;</NAME></OFX>")):
            self.assertEqual(parse_document(raw).root.children[0].text, expected)

    def test_entity_decoding_is_not_recursive(self):
        for raw in (sgml("<OFX><NAME>&amp;lt;</OFX>"), xml("<OFX><NAME>&amp;lt;</NAME></OFX>")):
            self.assertEqual(parse_document(raw).root.children[0].text, "&lt;")

    def test_unknown_extension_shapes(self):
        result = parse_document(sgml("<OFX><EXT>text<BOX><OTHER>value</OTHER></BOX><EMPTY></EMPTY></OFX>"))
        self.assertEqual(result.root.children[0].text, "text")
        self.assertEqual(result.root.children[1].children[0].tag, "OTHER")
        self.assertEqual(result.root.children[2].text, "")

    def test_unknown_empty_unclosed_is_ambiguous(self):
        self.assert_code("sgml_ambiguous", sgml("<OFX><EXT></OFX>"))

    def test_header_duplicate(self):
        self.assert_code("duplicate_header", sgml().replace(b"VERSION:102", b"VERSION:102\nVERSION:102"))
        self.assert_code("duplicate_header", xml().replace(b'VERSION="220"', b'VERSION="220" VERSION="220"'))

    def test_pi_attributes_reject_non_xml_whitespace(self):
        self.assert_code("invalid_header", xml().replace(b'OFXHEADER="200"', b'OFXHEADER\x0c="200"'))
        self.assert_code("invalid_header", xml().replace(b'OFXHEADER="200"', b'OFXHEADER=\x0b"200"'))

    def test_header_required_and_extra(self):
        self.assert_code("missing_header", sgml().replace(b"NEWFILEUID:NONE\n", b""))
        self.assert_code("invalid_header", sgml().replace(b"NEWFILEUID:NONE", b"NEWFILEUID:NONE\nUNKNOWN:NONE"))
        self.assert_code("invalid_header", xml().replace(b' NEWFILEUID="NONE"', b""))
        self.assert_code("invalid_header", xml().replace(b' NEWFILEUID="NONE"', b' NEWFILEUID="NONE" EXTRA="X"'))

    def test_security_compression_and_encoding(self):
        self.assert_code("unsupported_security", sgml().replace(b"SECURITY:NONE", b"SECURITY:TYPE1"))
        self.assert_code("unsupported_security", sgml().replace(b"COMPRESSION:NONE", b"COMPRESSION:GZIP"))
        self.assert_code("unsupported_security", xml().replace(b'SECURITY="NONE"', b'SECURITY="TYPE1"'))
        self.assert_code("unsupported_encoding", sgml().replace(b"ENCODING:UTF-8", b"ENCODING:UNICODE"))
        self.assert_code("unsupported_encoding", xml().replace(b'encoding="UTF-8"', b'encoding="UTF-16"'))

    def test_versions_do_not_guess_title(self):
        self.assert_code("unsupported_version", xml(version="230"))
        self.assert_code("unsupported_version", sgml(version="200"))

    def test_invalid_encoding_is_not_replaced(self):
        self.assert_code("invalid_encoding", sgml().replace(b"Exemplo", b"\xff"))
        self.assert_code("malformed_xml", xml().replace(b"Exemplo", b"\xff"))

    def test_xml_header_is_required(self):
        self.assert_code("missing_header", b"<OFX/>")
        self.assert_code("missing_header", b'<?xml version="1.0"?><OFX/>')
        self.assert_code("duplicate_header", xml().replace(b'<?xml version="1.0"', b'<?xml version="1.0" version="1.0"'))

    def test_xml_comments_cdata_and_no_pi(self):
        result = parse_document(xml("<OFX><!--nota--><MEMO><![CDATA[A & B < C]]></MEMO></OFX>"))
        self.assertEqual(result.root.children[0].text, "A & B < C")
        self.assert_code("unsupported_processing_instruction", xml("<OFX><?demo segredo?></OFX>"))

    def test_dtd_and_entity_definitions_blocked(self):
        self.assert_code("unsafe_xml", xml('<!DOCTYPE OFX [<!ENTITY x "abc">]><OFX><NAME>&x;</NAME></OFX>'))
        self.assert_code("unsafe_xml", xml('<!DOCTYPE OFX SYSTEM "https://example.invalid/no-network.dtd"><OFX/>'))
        self.assert_code("unsafe_markup", sgml('<!DOCTYPE OFX><OFX></OFX>'))

    def test_attributes_and_namespace_blocked(self):
        self.assert_code("unsupported_attributes", xml('<OFX x="1"/>'))
        self.assert_code("unsupported_namespace", xml('<OFX xmlns="urn:demo"/>'))
        self.assert_code("unsupported_namespace", xml('<OFX xmlns:x="urn:demo"/>'))
        self.assert_code("unsupported_namespace", sgml("<OFX><x:NAME>x</x:NAME></OFX>"))

    def test_xml_tag_case_is_significant(self):
        self.assert_code("invalid_tag", xml("<OFX><name>x</name></OFX>"))

    def test_known_sgml_aggregate_must_close(self):
        self.assert_code("mismatched_aggregate", sgml("<OFX><STATUS><CODE>0</OFX>"))
        self.assert_code("unclosed_aggregate", sgml("<OFX><STATUS><CODE>0</STATUS>"))

    def test_multiple_roots_trailing_data(self):
        self.assert_code("trailing_content", sgml("<OFX></OFX><OFX></OFX>"))
        self.assert_code("malformed_xml", xml("<OFX/><OFX/>"))
        with self.assertRaises(OfxError):
            parse_document(sgml("<OFX></OFX>untrusted"))

    def test_mixed_content_rejected(self):
        for body in ("<OFX>bad<NAME>x</NAME></OFX>", "<OFX><NAME>x</NAME>bad</OFX>"):
            self.assert_code("mixed_content", sgml(body))
            self.assert_code("mixed_content", xml(body))
        self.assert_code("mixed_content", xml("<OFX>\u00a0<NAME>x</NAME></OFX>"))

    def test_illegal_chars_and_entities(self):
        for value in ("&#0;", "&#xD800;", "&#x110000;", "&#xFFFE;", "&nbsp;", "a&b", "&#9999999999999999999999;"):
            with self.subTest(value=value):
                with self.assertRaises(OfxError):
                    parse_document(sgml(f"<OFX><NAME>{value}</OFX>"))
                with self.assertRaises(OfxError):
                    parse_document(xml(f"<OFX><NAME>{value}</NAME></OFX>"))
        self.assert_code("invalid_character", sgml("<OFX><NAME>\x01</OFX>"))

    def test_node_depth_input_and_leaf_limits(self):
        for factory, body in ((sgml, "<OFX><NAME>abcdefghi</OFX>"), (xml, "<OFX><NAME>abcdefghi</NAME></OFX>")):
            raw = factory(body)
            self.assert_code("input_limit", raw, limits=replace(Limits(), max_input_bytes=len(raw) - 1))
            self.assert_code("node_limit", raw, limits=replace(Limits(), max_nodes=1))
            self.assert_code("depth_limit", raw, limits=replace(Limits(), max_depth=1))
            self.assert_code("text_limit", raw, limits=replace(Limits(), max_text_chars=8))
            self.assertEqual(parse_document(raw, limits=replace(Limits(), max_input_bytes=len(raw), max_nodes=2, max_depth=2, max_text_chars=9)).stats.nodes, 2)

    def test_decoded_leaf_limit(self):
        for factory, body in ((sgml, "<OFX><NAME>&amp;&amp;&amp;&amp;</OFX>"), (xml, "<OFX><NAME>&amp;&amp;&amp;&amp;</NAME></OFX>")):
            self.assertEqual(parse_document(factory(body), limits=replace(Limits(), max_text_chars=4)).root.children[0].text, "&&&&")
            self.assert_code("text_limit", factory(body), limits=replace(Limits(), max_text_chars=3))

    def test_tiny_leaf_budget_does_not_apply_to_fixed_header(self):
        for raw in (sgml("<OFX><NAME>x</OFX>"), xml("<OFX><NAME>x</NAME></OFX>")):
            self.assertEqual(parse_document(raw, limits=replace(Limits(), max_text_chars=1)).root.children[0].text, "x")

    def test_xml_feed_boundary_and_whitespace_prefix(self):
        name = "ó" * 4096
        result = parse_document(xml(f"<OFX><NAME>{name}</NAME></OFX>"))
        self.assertEqual(result.root.children[0].text, name)
        self.assert_code("text_limit", xml(f"<OFX><NAME>{name}a</NAME></OFX>"))
        self.assert_code("text_limit", xml("<OFX><NAME>" + " " * 9000 + "x</NAME></OFX>"))

    def test_ascii_numeric_characters_against_xml(self):
        for number in range(128):
            sgml_raw = sgml(f"<OFX><NAME>&#{number};</OFX>")
            xml_raw = xml(f"<OFX><NAME>&#{number};</NAME></OFX>")
            with self.subTest(number=number):
                if number in {9, 10, 13} or number >= 32:
                    self.assertEqual(parse_document(sgml_raw).root.children[0].text, parse_document(xml_raw).root.children[0].text)
                else:
                    with self.assertRaises(OfxError):
                        parse_document(sgml_raw)
                    with self.assertRaises(OfxError):
                        parse_document(xml_raw)

    def test_aggregate_formatting_not_retained_or_leaf_limited(self):
        space = " " * 5000
        for factory in (sgml, xml):
            result = parse_document(factory(f"<OFX>{space}<NAME>x</NAME>{space}</OFX>"))
            self.assertEqual(result.root.text, "")
            self.assertEqual(result.root.children[0].text, "x")
            self.assertGreaterEqual(result.stats.text_characters, 10001)

    def test_large_unknown_prefix_is_streamed(self):
        result = parse_document(sgml("<OFX><EXT>" + "&#32;" * 5000 + "<NAME>x</NAME></EXT></OFX>"))
        self.assertEqual(result.root.children[0].text, "")
        self.assert_code("text_limit", sgml("<OFX><EXT>" + "&#65;" * 5000 + "</EXT></OFX>"))

    def test_empty_leaf_and_empty_root(self):
        self.assertEqual(parse_document(sgml("<OFX><NAME></OFX>")).root.children[0].text, "")
        self.assertEqual(parse_document(xml("<OFX/>")).root.children, ())

    def test_strict_input_type_and_empty(self):
        self.assert_code("invalid_input_type", "<OFX>")
        self.assert_code("invalid_input_type", bytearray(b"OFX"))
        self.assert_code("empty_input", b"")
        self.assert_code("invalid_limits", sgml(), limits={})

    def test_transport_object_is_frozen(self):
        document = parse_document(xml())
        with self.assertRaises(AttributeError):
            document.root.text = "changed"
        with self.assertRaises(AttributeError):
            document.header.version = "230"


if __name__ == "__main__":
    unittest.main()
