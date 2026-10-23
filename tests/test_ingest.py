"""Canonical CSV contracts, independent of reconciliation calculations."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from settletrace.ingest import (
    load_deposits, load_entries, load_sales,
    parse_deposits, parse_entries, parse_sales,
)
from settletrace.models import InputError


SALES_HEADER = "sale_id,payment_ref,currency,gross_minor\n"
ENTRY_HEADER = "transaction_id,payment_ref,payout_id,kind,currency,gross_minor,fee_minor,net_minor\n"
BANK_HEADER = "bank_ref,payout_id,currency,amount_minor\n"


class IngestionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def fixture(self, text, *, name="input.csv", encoding="utf-8"):
        path = self.directory / name
        path.write_text(text, encoding=encoding, newline="")
        return path

    def assert_invalid(self, text, *, loader=load_sales, line=2, message=None):
        path = self.fixture(text)
        with self.assertRaises(InputError) as caught:
            loader(path)
        error = str(caught.exception)
        self.assertIn(f"{path}:{line}:", error)
        if message:
            self.assertIn(message, error)

    def test_sales_preserve_exact_amounts_identifiers_and_source_lines(self):
        path = self.fixture(SALES_HEADER + "sale-é,pay_1,INR,12345678901234567890\n")
        records = load_sales(str(path))
        self.assertEqual(len(records), 1)
        sale = records[0]
        self.assertEqual(sale.sale_id, "sale-é")
        self.assertEqual(sale.payment_ref, "pay_1")
        self.assertEqual(sale.currency, "INR")
        self.assertEqual(sale.gross_minor, 12345678901234567890)
        self.assertIs(type(sale.gross_minor), int)
        self.assertEqual(sale.row, 2)

    def test_processor_loads_signed_refunds_and_fees(self):
        path = self.fixture(
            ENTRY_HEADER
            + "tx_1,pay_1,payout_1,charge,USD,10000,300,9700\n"
            + "tx_2,pay_1,payout_1,refund,USD,-1000,-30,-970\n"
            + "tx_3,,payout_1,fee,USD,0,25,-25\n"
        )
        entries = load_entries(path)
        self.assertEqual([(entry.gross_minor, entry.fee_minor, entry.net_minor) for entry in entries],
                         [(10000, 300, 9700), (-1000, -30, -970), (0, 25, -25)])
        self.assertEqual([entry.row for entry in entries], [2, 3, 4])
        self.assertEqual(entries[2].payment_ref, "")

    def test_processor_does_not_infer_missing_payout_reference(self):
        path = self.fixture(ENTRY_HEADER + "tx_1,pay_1,,charge,USD,100,3,97\n")
        self.assertEqual(load_entries(path)[0].payout_id, "")

    def test_bank_loads_explicit_references(self):
        path = self.fixture(BANK_HEADER + "bank_1,payout_1,GBP,9700\n")
        deposit = load_deposits(path)[0]
        self.assertEqual((deposit.bank_ref, deposit.payout_id, deposit.currency, deposit.amount_minor, deposit.row),
                         ("bank_1", "payout_1", "GBP", 9700, 2))

    def test_header_order_can_vary(self):
        path = self.fixture("currency,gross_minor,payment_ref,sale_id\nEUR,100,pay_1,sale_1\n")
        self.assertEqual(load_sales(path)[0].sale_id, "sale_1")

    def test_utf8_bom_is_accepted_only_at_file_start(self):
        path = self.fixture(SALES_HEADER + "sale_1,pay_1,USD,100\n", encoding="utf-8-sig")
        self.assertEqual(load_sales(path)[0].gross_minor, 100)
        self.assert_invalid("sale_id,\ufeffpayment_ref,currency,gross_minor\ns,p,USD,100\n",
                            line=1, message="unexpected columns")

    def test_crlf_and_quoted_cells_are_supported(self):
        path = self.fixture('sale_id,payment_ref,currency,gross_minor\r\n"sale,1","pay,1",USD,100\r\n')
        sale = load_sales(path)[0]
        self.assertEqual((sale.sale_id, sale.payment_ref, sale.row), ("sale,1", "pay,1", 2))

    def test_multiline_record_evidence_is_ending_physical_line(self):
        path = self.fixture(SALES_HEADER + '"sale\n1",pay_1,USD,100\n')
        sale = load_sales(path)[0]
        self.assertEqual(sale.sale_id, "sale\n1")
        self.assertEqual(sale.row, 3)

    def test_blank_separator_lines_preserve_actual_evidence(self):
        path = self.fixture(SALES_HEADER + "\nsale_1,pay_1,USD,100\n\nsale_2,pay_2,USD,200\n")
        self.assertEqual([sale.row for sale in load_sales(path)], [3, 5])

    def test_header_only_files_are_deliberately_empty_datasets(self):
        for header, loader in ((SALES_HEADER, load_sales), (ENTRY_HEADER, load_entries), (BANK_HEADER, load_deposits)):
            with self.subTest(loader=loader.__name__):
                self.assertEqual(loader(self.fixture(header)), [])

    def test_wholly_empty_file_is_not_an_empty_dataset(self):
        self.assert_invalid("", line=1, message="empty file")

    def test_each_schema_requires_all_its_columns(self):
        for header, loader in ((SALES_HEADER, load_sales), (ENTRY_HEADER, load_entries), (BANK_HEADER, load_deposits)):
            with self.subTest(loader=loader.__name__):
                shortened = ",".join(header.strip().split(",")[:-1]) + "\n"
                self.assert_invalid(shortened, loader=loader, line=1, message="missing columns")

    def test_unexpected_header_column_is_rejected(self):
        self.assert_invalid(SALES_HEADER.rstrip() + ",comment\n", line=1, message="unexpected columns")

    def test_duplicate_header_is_rejected_even_when_name_is_expected(self):
        self.assert_invalid(SALES_HEADER.rstrip() + ",sale_id\n", line=1, message="duplicate column")

    def test_header_names_are_not_trimmed_or_case_folded(self):
        for header in (" sale_id,payment_ref,currency,gross_minor\n", "Sale_id,payment_ref,currency,gross_minor\n"):
            with self.subTest(header=header):
                self.assert_invalid(header, line=1, message="missing columns")

    def test_excess_row_cells_are_rejected(self):
        self.assert_invalid(SALES_HEADER + "sale_1,pay_1,USD,100,unexpected\n", message="more cells")

    def test_missing_row_cells_are_rejected(self):
        self.assert_invalid(SALES_HEADER + "sale_1,pay_1,USD\n", message="fewer cells")

    def test_empty_required_identifiers_are_rejected_by_models_with_location(self):
        for row in (",pay_1,USD,100\n", "sale_1,,USD,100\n"):
            with self.subTest(row=row):
                self.assert_invalid(SALES_HEADER + row, message="nonblank string")

    def test_identifiers_are_not_trimmed(self):
        for row in (" sale_1,pay_1,USD,100\n", "sale_1,pay_1 ,USD,100\n"):
            with self.subTest(row=row):
                self.assert_invalid(SALES_HEADER + row, message="surrounding whitespace")

    def test_currency_must_be_supported_and_exact_uppercase(self):
        for currency in ("usd", "USD ", "JPY", "", "USd"):
            with self.subTest(currency=currency):
                self.assert_invalid(SALES_HEADER + f"sale_1,pay_1,{currency},100\n")

    def test_amount_requires_ascii_integer_minor_units(self):
        for amount in ("10.00", "1e2", '"1,000"', "True", "False", "NaN", "Infinity", "", " 100", "100 ", "١٠٠", "1_000"):
            with self.subTest(amount=amount):
                self.assert_invalid(SALES_HEADER + f"sale_1,pay_1,USD,{amount}\n", message="integer in minor units")

    def test_each_processor_amount_field_is_validated(self):
        values = ["100", "3", "97"]
        for index, field in enumerate(("gross_minor", "fee_minor", "net_minor")):
            invalid = values.copy()
            invalid[index] = "1.5"
            with self.subTest(field=field):
                self.assert_invalid(ENTRY_HEADER + "tx_1,pay_1,payout_1,charge,USD," + ",".join(invalid) + "\n",
                                    loader=load_entries, message=field)

    def test_bank_amount_is_validated(self):
        self.assert_invalid(BANK_HEADER + "bank_1,payout_1,USD,10.5\n", loader=load_deposits, message="amount_minor")

    def test_model_failure_keeps_file_and_line(self):
        self.assert_invalid(ENTRY_HEADER + "tx_1,pay_1,payout_1,charge,USD,100,3,99\n",
                            loader=load_entries, message="net_minor must equal")

    def test_malformed_quoted_csv_is_rejected(self):
        self.assert_invalid(SALES_HEADER + '"sale_1,pay_1,USD,100\n', message="invalid CSV")

    def test_malformed_multiline_error_points_to_record_ending_line(self):
        self.assert_invalid(SALES_HEADER + '"sale\n1",pay_1,USD,10.5\n', line=3, message="integer in minor units")

    def test_invalid_utf8_is_reported_as_input_error(self):
        path = self.directory / "invalid.csv"
        path.write_bytes(b"\xff")
        with self.assertRaises(InputError) as caught:
            load_sales(path)
        self.assertIn(f"{path}:1:", str(caught.exception))
        self.assertIn("UTF-8", str(caught.exception))

    def test_invalid_utf8_after_valid_records_reports_actual_physical_line(self):
        for newline in (b"\n", b"\r\n", b"\r"):
            with self.subTest(newline=newline):
                path = self.directory / "invalid.csv"
                path.write_bytes(newline.join([
                    SALES_HEADER.rstrip().encode("utf-8"),
                    b"sale_1,pay_1,USD,100",
                    b"sale_\xff,pay_2,USD,100",
                ]))
                with self.assertRaises(InputError) as caught:
                    load_sales(path)
                self.assertIn(f"{path}:3:", str(caught.exception))

    def test_missing_file_is_a_file_error(self):
        with self.assertRaises(FileNotFoundError):
            load_sales(self.directory / "does-not-exist.csv")

    def test_byte_parsers_load_exact_snapshots_for_all_schemas(self):
        cases = (
            (parse_sales, SALES_HEADER + "s,p,USD,100\n", "gross_minor", 100),
            (parse_entries, ENTRY_HEADER + "t,p,po,charge,USD,100,3,97\n", "net_minor", 97),
            (parse_deposits, BANK_HEADER + "b,po,USD,97\n", "amount_minor", 97),
        )
        for parser, text, field, expected in cases:
            with self.subTest(parser=parser.__name__):
                record = parser(text.encode("utf-8-sig"), "snapshot.csv")[0]
                self.assertEqual(getattr(record, field), expected)
                self.assertEqual(record.row, 2)

    def test_snapshot_parsing_never_reopens_replaced_source_path(self):
        path = self.fixture(SALES_HEADER + "s,p,USD,100\n")
        snapshot = path.read_bytes()
        path.write_text(SALES_HEADER + "s,p,USD,999\n", encoding="utf-8")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("parser reopened source")):
            sale = parse_sales(snapshot, str(path))[0]
        self.assertEqual(sale.gross_minor, 100)

    def test_each_path_loader_reads_input_exactly_once(self):
        cases = (
            (load_sales, SALES_HEADER + "s,p,USD,100\n"),
            (load_entries, ENTRY_HEADER + "t,p,po,charge,USD,100,3,97\n"),
            (load_deposits, BANK_HEADER + "b,po,USD,97\n"),
        )
        for loader, text in cases:
            with self.subTest(loader=loader.__name__):
                with patch.object(Path, "read_bytes", return_value=text.encode("utf-8")) as read:
                    self.assertEqual(len(loader("supplied.csv")), 1)
                read.assert_called_once_with()

    def test_snapshot_errors_keep_source_label_and_physical_line(self):
        with self.assertRaises(InputError) as caught:
            parse_sales((SALES_HEADER + '"sale\n1",pay,USD,1.5\n').encode("utf-8"), "captured.csv")
        self.assertIn("captured.csv:3:", str(caught.exception))
        with self.assertRaises(InputError) as caught:
            parse_sales(SALES_HEADER.encode("utf-8") + b"s,p,USD,100\ns\xff,p,USD,100\n", "captured.csv")
        self.assertIn("captured.csv:3:", str(caught.exception))

    def test_snapshot_requires_immutable_bytes(self):
        with self.assertRaisesRegex(TypeError, "immutable bytes"):
            parse_sales(bytearray(SALES_HEADER.encode("utf-8")), "captured.csv")


if __name__ == "__main__":
    unittest.main()
