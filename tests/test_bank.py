"""Explicit payout mapping rejects ambiguity instead of matching by amount."""

import unittest

from settletrace.bank import map_bank
from settletrace.models import InputError


BANK_HEADER = "bank_ref,currency,amount_minor\n"
MAPPING_HEADER = "bank_ref,payout_id\n"


class BankMappingTests(unittest.TestCase):
    def mapped(self, bank="b1,USD,7650\n", mapping="b1,po1\n"):
        return map_bank((BANK_HEADER + bank).encode(), (MAPPING_HEADER + mapping).encode(),
                        "bank-input.csv", "chosen.csv")

    def test_explicit_reference_wins_over_equal_amount_and_mapping_order(self):
        deposits, audit = self.mapped("b1,USD,7650\nb2,USD,7650\n", "b2,po1\nb1,po2\n")
        self.assertEqual([(d.bank_ref, d.payout_id, d.amount_minor, d.row) for d in deposits],
                         [("b1", "po2", 7650, 2), ("b2", "po1", 7650, 3)])
        self.assertEqual(audit, [dict(bank_ref="b1", payout_id="po2", bank_row=2, mapping_row=3),
                                 dict(bank_ref="b2", payout_id="po1", bank_row=3, mapping_row=2)])

    def test_header_order_bom_quotes_and_multiline_ending_rows(self):
        deposits, audit = map_bank(
            '\ufeffamount_minor,currency,bank_ref\r\n\r\n-25,EUR,"bank\n1"\r\n'.encode(),
            '\ufeffpayout_id,bank_ref\n"po,1","bank\n1"\n'.encode())
        self.assertEqual((deposits[0].bank_ref, deposits[0].payout_id, deposits[0].row),
                         ("bank\n1", "po,1", 4))
        self.assertEqual(audit[0]["mapping_row"], 3)

    def test_negative_zero_and_large_exact_amounts_are_preserved(self):
        for amount in ("-7650", "0", "+0", "-0", "9" * 128):
            with self.subTest(amount=amount):
                deposits, _ = self.mapped(f"b1,INR,{amount}\n")
                self.assertEqual(deposits[0].amount_minor, int(amount))
                self.assertIs(type(deposits[0].amount_minor), int)

    def test_bank_identifiers_cannot_repeat(self):
        with self.assertRaisesRegex(InputError, "bank-input.csv:3: duplicate bank_ref"):
            self.mapped("b1,USD,1\nb1,USD,2\n")

    def test_mapping_cannot_split_one_bank_record(self):
        with self.assertRaisesRegex(InputError, "chosen.csv:3: duplicate bank_ref"):
            self.mapped(mapping="b1,po1\nb1,po2\n")

    def test_payout_cannot_be_aggregated_across_bank_records(self):
        with self.assertRaisesRegex(InputError, "chosen.csv:3: duplicate payout_id"):
            self.mapped("b1,USD,1\nb2,USD,2\n", "b1,po1\nb2,po1\n")

    def test_unmapped_bank_record_is_not_ignored(self):
        with self.assertRaisesRegex(InputError, "bank-input.csv:3:.*no explicit payout mapping"):
            self.mapped("b1,USD,1\nb2,USD,2\n")

    def test_unknown_mapping_reference_is_not_ignored(self):
        with self.assertRaisesRegex(InputError, "chosen.csv:2:.*was not observed"):
            self.mapped(mapping="b2,po1\n")

    def test_header_only_bank_and_mapping_are_not_success(self):
        for bank, mapping in (("", ""), ("", "b1,po1\n"), ("b1,USD,1\n", "")):
            with self.subTest(bank=bank, mapping=mapping), self.assertRaises(InputError):
                self.mapped(bank, mapping)

    def test_currency_and_noncanonical_money_are_rejected(self):
        for currency, amount in (("usd", "1"), ("JPY", "1"), ("USD", "1.00"), ("USD", "1e2"),
                                 ("USD", "١"), ("USD", "9" * 129), ("USD", "9" * 5000)):
            with self.subTest(currency=currency, amount=amount), self.assertRaisesRegex(InputError, "bank-input.csv:2:"):
                self.mapped(f"b1,{currency},{amount}\n")

    def test_width_must_match_in_both_inputs(self):
        for bank, mapping, label in (("b1,USD\n", "b1,po1\n", "bank-input.csv"),
                                     ("b1,USD,1,extra\n", "b1,po1\n", "bank-input.csv"),
                                     ("b1,USD,1\n", "b1\n", "chosen.csv"),
                                     ("b1,USD,1\n", "b1,po1,extra\n", "chosen.csv")):
            with self.subTest(bank=bank, mapping=mapping), self.assertRaisesRegex(InputError, label + ":2:.*width"):
                self.mapped(bank, mapping)

    def test_blank_padded_identifiers_and_amounts_are_not_normalized(self):
        for bank, mapping in ((",USD,1\n", "b1,po1\n"), (" b1,USD,1\n", "b1,po1\n"),
                              ("b1,USD,1 \n", "b1,po1\n"), ("b1,USD,1\n", "b1,\n"),
                              ("b1,USD,1\n", "b1,po1 \n"), ("b1,USD,1\n", " ,po1\n")):
            with self.subTest(bank=bank, mapping=mapping), self.assertRaises(InputError):
                self.mapped(bank, mapping)

    def test_exact_headers_required_including_duplicate_detection(self):
        good_bank = (BANK_HEADER + "b1,USD,1\n").encode()
        good_mapping = (MAPPING_HEADER + "b1,po1\n").encode()
        for bank in (b"", b"bank_ref,currency,amount_minor,bank_ref\n", b"bank_ref,currency\n",
                     b"bank_ref,currency,amount_minor,note\n", b"Bank_ref,currency,amount_minor\n"):
            with self.subTest(bank=bank), self.assertRaisesRegex(InputError, "bank.csv:1:"):
                map_bank(bank, good_mapping)
        for mapping in (b"", b"bank_ref,payout_id,bank_ref\n", b"bank_ref\n", b"bank_ref,payout_id,note\n"):
            with self.subTest(mapping=mapping), self.assertRaisesRegex(InputError, "mapping.csv:1:"):
                map_bank(good_bank, mapping)

    def test_invalid_utf8_and_malformed_quoted_csv_include_source_location(self):
        for bank in (BANK_HEADER.encode() + b"\xff", BANK_HEADER.encode() + b'"unfinished'):
            with self.subTest(bank=bank), self.assertRaisesRegex(InputError, "bank.csv:2:"):
                map_bank(bank, (MAPPING_HEADER + "b1,po1\n").encode())
        for mapping in (MAPPING_HEADER.encode() + b"\xff", MAPPING_HEADER.encode() + b'"unfinished'):
            with self.subTest(mapping=mapping), self.assertRaisesRegex(InputError, "mapping.csv:2:"):
                map_bank((BANK_HEADER + "b1,USD,1\n").encode(), mapping)

    def test_mutable_snapshots_are_refused(self):
        with self.assertRaises(TypeError):
            map_bank(bytearray(BANK_HEADER.encode()), MAPPING_HEADER.encode())
        with self.assertRaises(TypeError):
            map_bank(BANK_HEADER.encode(), bytearray(MAPPING_HEADER.encode()))
