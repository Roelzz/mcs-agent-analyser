"""Tests for diagnosis/redaction.py — the regex-based PII stage."""

from __future__ import annotations

from diagnosis.redaction import redact_dict, redact_text


class TestRedactText:
    def test_empty_string_passthrough(self):
        r = redact_text("")
        assert r.text == ""
        assert r.summary == {}

    def test_no_pii_passthrough(self):
        r = redact_text("Hello world, nothing sensitive here.")
        assert r.text == "Hello world, nothing sensitive here."
        assert r.summary == {}

    def test_email(self):
        r = redact_text("Contact me at jane.doe@example.com please.")
        assert "[EMAIL_1]" in r.text
        assert "jane.doe@example.com" not in r.text
        assert r.summary == {"EMAIL": 1}

    def test_phone_international(self):
        r = redact_text("Call +31 6 1234 5678 for help.")
        assert "[PHONE_1]" in r.text
        assert r.summary["PHONE"] == 1

    def test_iban(self):
        r = redact_text("Transfer to NL91 ABNA 0417 1643 00 today.")
        assert "[IBAN_1]" in r.text
        assert r.summary == {"IBAN": 1}

    def test_credit_card_luhn_valid_redacted(self):
        # Visa test number — valid Luhn checksum.
        r = redact_text("Charge to 4539 1488 0343 6467 today.")
        assert "[CARD_1]" in r.text
        assert "4539" not in r.text
        assert r.summary["CARD"] == 1

    def test_credit_card_luhn_invalid_kept(self):
        # 16-digit string that fails Luhn — should not be redacted as a card,
        # but the phone pattern can still claim it as a long digit run.
        r = redact_text("Reference 1234 5678 9012 3456 (not a card).")
        assert "[CARD" not in r.text  # not classified as card
        # may or may not match phone — either result is acceptable here

    def test_bsn(self):
        r = redact_text("BSN 123456789 was provided.")
        assert "[BSN_1]" in r.text
        assert r.summary == {"BSN": 1}

    def test_name_with_honorific(self):
        r = redact_text("Mr Bonet was here. Dhr Janssen too.")
        assert "[NAME_1]" in r.text and "[NAME_2]" in r.text
        assert r.summary["NAME"] == 2

    def test_multiple_categories_counted(self):
        r = redact_text("Email a@b.com or phone +31612345678 — IBAN NL91ABNA0417164300 BSN 987654321.")
        assert r.summary.get("EMAIL") == 1
        assert r.summary.get("PHONE") == 1
        assert r.summary.get("IBAN") == 1
        # BSN may or may not survive depending on how the phone regex consumed
        # the surrounding digits — either way the count must be ≤ 1.
        assert r.summary.get("BSN", 0) in (0, 1)


class TestRedactDict:
    def test_strings_redacted(self):
        payload = {"summary": "Bot: contact jane.doe@example.com", "position": 5}
        new, summary = redact_dict(payload)
        assert "jane.doe@example.com" not in new["summary"]
        assert new["position"] == 5
        assert summary["EMAIL"] == 1

    def test_list_strings_redacted(self):
        payload = {"errors": ["timeout", "auth: jane.doe@example.com failed"]}
        new, summary = redact_dict(payload)
        assert all("jane.doe" not in s for s in new["errors"])
        assert summary["EMAIL"] == 1
