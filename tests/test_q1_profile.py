"""Q1.1 手算样本；所有行都是测试夹具，不是业务数据。"""

import math
import csv
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from q1_data_quality.q1_code import profile_frame
from scripts.q1_reference import reference_profile

COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
ROWS = [
    ["001", "001", " apple ", "1", "2020-01-01 00:00:00", "1", "001", "UK"],
    ["002", "001", "apple", "2", "2020-01-02 00:00:00", "2", "002", "UK"],
    ["003", "002", "", "3", "2020-01-03 00:00:00", "3", "", "FR"],
    ["C004", "POST", "x", "-1", "bad", "-1", "", "NA"],
    ["005", "003", " ", "", "2020-01-05 00:00:00", "0", "NULL", "FR"],
    ["006", "004", "x", "bad", "", "NaN", "004", ""],
]


class Q1ProfileTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(ROWS, columns=COLUMNS, dtype=str)
        self.result = profile_frame(self.frame)

    def test_every_row_and_column_is_counted(self):
        self.assertEqual(self.result["rows"], 6)
        self.assertEqual(list(self.result["columns"]), COLUMNS)

    def test_missing_denominator_and_literal_null_are_distinct(self):
        customer = self.result["columns"]["Customer ID"]
        self.assertEqual(customer["missing_count"], 2)
        self.assertEqual(customer["missing_fraction"], 2 / 6)
        self.assertEqual(customer["unique_nonempty"], 4)
        self.assertIn({"value": "NULL", "count": 1}, customer["top10"])

    def test_numeric_statistics_follow_hand_calculation(self):
        quantity = self.result["columns"]["Quantity"]["numeric"]
        self.assertEqual(quantity["valid_count"], 4)
        self.assertEqual(quantity["invalid_nonempty_count"], 1)
        self.assertEqual(quantity["min"], -1)
        self.assertEqual(quantity["max"], 3)
        self.assertEqual(quantity["mean"], 1.25)
        # (1-1.25)^2+(2-1.25)^2+(3-1.25)^2+(-1-1.25)^2 = 8.75。
        self.assertAlmostEqual(quantity["std"], math.sqrt(8.75 / 3), places=12)
        price = self.result["columns"]["Price"]["numeric"]
        self.assertEqual(price["valid_count"], 5)
        self.assertEqual(price["invalid_nonempty_count"], 1)
        self.assertEqual(price["mean"], 1)
        self.assertAlmostEqual(price["std"], math.sqrt(10 / 4), places=12)

    def test_whitespace_and_ties_are_preserved(self):
        description = self.result["columns"]["Description"]
        self.assertEqual(description["missing_count"], 1)
        self.assertEqual(description["whitespace_only_count"], 1)
        self.assertEqual(description["unique_nonempty"], 4)
        self.assertEqual(description["top10"], [
            {"value": "x", "count": 2}, {"value": " ", "count": 1},
            {"value": " apple ", "count": 1}, {"value": "apple", "count": 1}])
        self.assertEqual(self.result["columns"]["Country"]["top10"], [
            {"value": "FR", "count": 2}, {"value": "UK", "count": 2}, {"value": "NA", "count": 1}])

    def test_diagnostics_are_counts_not_business_labels(self):
        d = self.result["diagnostics"]
        self.assertEqual(d["negative_quantity"], 1)
        self.assertEqual(d["negative_price"], 1)
        self.assertEqual(d["zero_price"], 1)
        self.assertEqual(d["non_numeric_invoice"], 1)
        self.assertEqual(d["unusual_stock_format"], 1)
        self.assertEqual(d["description_edge_whitespace"], 2)
        self.assertEqual(d["duplicate_extra_rows"], 0)
        self.assertEqual(self.result["dates"]["invalid_nonempty_count"], 1)

    def test_permuting_input_does_not_change_profile(self):
        self.assertEqual(profile_frame(self.frame.iloc[::-1]), self.result)

    def test_duplicate_count_means_extra_occurrences(self):
        doubled = pd.concat([self.frame, self.frame.iloc[[0]], self.frame.iloc[[0]]])
        self.assertEqual(profile_frame(doubled)["diagnostics"]["duplicate_extra_rows"], 2)

    def test_single_numeric_value_has_no_sample_std(self):
        result = profile_frame(self.frame.iloc[[0]])
        self.assertIsNone(result["columns"]["Quantity"]["numeric"]["std"])

    def test_all_invalid_numeric_values_are_not_zero_filled(self):
        frame = self.frame.iloc[[0]].copy()
        frame["Quantity"] = "inf"
        metric = profile_frame(frame)["columns"]["Quantity"]["numeric"]
        self.assertEqual(metric["valid_count"], 0)
        self.assertEqual(metric["invalid_nonempty_count"], 1)
        self.assertIsNone(metric["mean"])

    def test_reference_implementation_also_matches_hand_calculation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.csv"
            with path.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerows([COLUMNS, *ROWS])
            reference = reference_profile(path)
        self.assertEqual(reference["rows"], 6)
        self.assertEqual(reference["columns"]["Customer ID"]["missing_count"], 2)
        self.assertEqual(reference["columns"]["Quantity"]["numeric"]["mean"], 1.25)
        self.assertAlmostEqual(reference["columns"]["Quantity"]["numeric"]["std"], math.sqrt(8.75 / 3), places=12)
        self.assertEqual(reference["columns"]["Country"]["top10"][0], {"value": "FR", "count": 2})


if __name__ == "__main__":
    unittest.main()
