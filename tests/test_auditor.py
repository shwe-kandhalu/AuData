import unittest

from auditor.claims import extract_claims
from pathlib import Path

from auditor.core import audit_pdf, audit_text, recompute_p_value


class AuditorTests(unittest.TestCase):
    def test_extracts_t_pattern(self):
        claims = extract_claims("The effect was significant, t(28) = 2.45, p = .021.")

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].kind, "t")
        self.assertEqual(claims[0].df1, 28)
        self.assertEqual(claims[0].statistic, 2.45)
        self.assertEqual(claims[0].reported_p, 0.021)

    def test_extracts_f_pattern(self):
        claims = extract_claims("ANOVA found F(2, 45) = 5.12, p = .010.")

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].kind, "F")
        self.assertEqual(claims[0].df1, 2)
        self.assertEqual(claims[0].df2, 45)

    def test_extracts_chi_square_pattern(self):
        claims = extract_claims("Group differed: χ²(1) = 3.84, p = .050.")

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].kind, "chi_square")
        self.assertEqual(claims[0].df1, 1)

    def test_recomputes_r_pattern(self):
        claims = extract_claims("Association was r(30) = .50, p = .005.")

        self.assertEqual(len(claims), 1)
        self.assertAlmostEqual(recompute_p_value(claims[0]), 0.00357, places=4)

    def test_flags_mismatch(self):
        findings = audit_text("The effect was t(28) = 2.45, p = .900.")

        self.assertEqual(findings[0].status, "mismatch")
        self.assertEqual(findings[0].note, "Reported p-value does not match the recomputed p-value.")

    def test_finding_contains_evidence_and_math_trace(self):
        text = "Results\nThe effect was t(28) = 2.45, p = .900, indicating a large difference."
        finding = audit_text(text)[0].to_dict()

        self.assertEqual(finding["claim"], "t(28) = 2.45, p = .900")
        self.assertEqual(finding["reported_p"], "=0.9")
        self.assertEqual(finding["evidence"]["section"], "Results")
        self.assertEqual(
            finding["evidence"]["quote"],
            "The effect was t(28) = 2.45, p = .900, indicating a large difference.",
        )
        self.assertEqual(finding["evidence"]["exact_quote"], "t(28) = 2.45, p = .900")
        self.assertEqual(finding["evidence"]["start_char"], text.index("t(28)"))
        self.assertLessEqual(finding["evidence"]["quote_start_char"], finding["evidence"]["start_char"])
        self.assertGreaterEqual(finding["evidence"]["quote_end_char"], finding["evidence"]["end_char"])
        self.assertEqual(finding["math"]["test"], "two_tailed_t_test")
        self.assertIn("t.cdf", finding["math"]["formula"])
        self.assertIn("substitution", finding["math"])
        self.assertEqual(finding["math"]["inputs"]["df"], 28)
        self.assertIn(finding["confidence"], {"High", "Medium", "Low"})
        self.assertGreater(finding["difference"], 0)

    def test_evidence_quote_skips_preceding_heading(self):
        text = "Sanity Test Paper\n\nResults\nParticipants improved, t(28) = 2.31, p = .029."
        finding = audit_text(text)[0].to_dict()

        self.assertEqual(
            finding["evidence"]["quote"],
            "Participants improved, t(28) = 2.31, p = .029.",
        )
        self.assertEqual(finding["evidence"]["section"], "Results")

    def test_pdf_audit_contains_page_trace(self):
        sample = Path("samples/test_paper.pdf")
        if not sample.exists():
            self.skipTest("sample PDF is not present")

        result = audit_pdf(sample)

        self.assertGreaterEqual(result["claim_count"], 1)
        self.assertGreaterEqual(result["findings"][0]["evidence"]["page"], 1)
        self.assertIn("quote", result["findings"][0]["evidence"])
        self.assertIn("exact_quote", result["findings"][0]["evidence"])
        self.assertIn("bboxes", result["findings"][0]["evidence"])


if __name__ == "__main__":
    unittest.main()
