# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_log_redaction.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import unittest

from hydra_umc_ops_agent.log_redaction import redact_lines, redact_secrets


class RedactSecretsTests(unittest.TestCase):
    def test_empty_and_none_like_input_is_returned_unchanged(self):
        self.assertEqual(redact_secrets(""), "")

    def test_plain_text_with_no_secret_is_unchanged(self):
        text = "service started on port 8080, uptime 42s"
        self.assertEqual(redact_secrets(text), text)

    def test_env_style_key_value_password_is_redacted(self):
        self.assertEqual(redact_secrets("DB_PASSWORD=hunter2"), "DB_PASSWORD=[REDACTED]")

    def test_quoted_key_value_is_redacted_without_leaking_the_quote_style(self):
        self.assertEqual(redact_secrets('api_key: "sk-real-looking-key-123"'), "api_key: [REDACTED]")
        self.assertEqual(redact_secrets("token = 'abc.def.ghi'"), "token = [REDACTED]")

    def test_case_insensitive_key_matching(self):
        self.assertEqual(redact_secrets("Secret=xyz"), "Secret=[REDACTED]")
        self.assertEqual(redact_secrets("API_KEY=xyz"), "API_KEY=[REDACTED]")

    def test_bearer_token_is_redacted(self):
        self.assertEqual(
            redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.real.signature"),
            "Authorization: Bearer [REDACTED]",
        )

    def test_pem_private_key_block_is_fully_redacted_body_included(self):
        block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpQIBAAKCAQEA1234567890abcdef\n"
            "-----END RSA PRIVATE KEY-----"
        )
        result = redact_secrets(f"before\n{block}\nafter")
        self.assertNotIn("MIIEpQIBAAKCAQEA1234567890abcdef", result)
        self.assertIn("[REDACTED]", result)
        self.assertIn("before", result)
        self.assertIn("after", result)

    def test_only_the_secret_value_is_redacted_not_the_whole_line(self):
        result = redact_secrets("startup: DB_PASSWORD=hunter2 db=main")
        self.assertIn("startup:", result)
        self.assertIn("db=main", result)
        self.assertNotIn("hunter2", result)

    def test_multiple_secrets_on_the_same_line_are_all_redacted(self):
        result = redact_secrets("user=alice password=hunter2 token=abc123")
        self.assertNotIn("hunter2", result)
        self.assertNotIn("abc123", result)
        self.assertIn("user=alice", result)

    # REV-013 regression: a real audit found these 3 real shapes escaping
    # every existing pattern above - never covered by a heuristic, each
    # gets its own real, explicit pattern (see log_redaction.py).
    def test_json_string_key_secret_is_redacted(self):
        result = redact_secrets('{"password":"AUDIT_FAKE_SECRET"}')
        self.assertNotIn("AUDIT_FAKE_SECRET", result)
        self.assertIn('"password":[REDACTED]', result)

    def test_json_string_key_secret_with_surrounding_whitespace_is_redacted(self):
        result = redact_secrets('{"apiKey": "AUDIT_FAKE_SECRET", "other": 1}')
        self.assertNotIn("AUDIT_FAKE_SECRET", result)
        self.assertIn('"other": 1', result)

    def test_url_userinfo_credential_is_redacted_but_username_kept(self):
        result = redact_secrets("https://audit:AUDIT_FAKE_SECRET@example.invalid/path")
        self.assertNotIn("AUDIT_FAKE_SECRET", result)
        self.assertIn("https://audit:[REDACTED]@example.invalid/path", result)

    def test_pem_block_split_across_multiple_log_lines_is_still_redacted(self):
        # The real gap: redact_lines() used to redact each list entry in
        # isolation, so a PEM whose BEGIN/END markers land in different
        # entries of a bounded log-line list never matched as one shape.
        lines = [
            "before",
            "-----BEGIN RSA PRIVATE KEY-----",
            "MIIEpQIBAAKCAQEA1234567890abcdef",
            "-----END RSA PRIVATE KEY-----",
            "after",
        ]
        result = redact_lines(lines)
        joined = "\n".join(result)
        self.assertNotIn("MIIEpQIBAAKCAQEA1234567890abcdef", joined)
        self.assertIn("[REDACTED]", joined)
        self.assertIn("before", joined)
        self.assertIn("after", joined)

    def test_a_secret_nested_one_level_deeper_as_a_json_object_is_redacted(self):
        # V07-010 (found in an independent revalidation audit, P1,
        # residual outside REV-013's own three original examples): the
        # secret's own value used to be required to be an immediate
        # quoted string/scalar - a real "password": {"value": "FAKE"}
        # shape (a nested object) let FAKE slip through untouched.
        result = redact_secrets('{"password": {"value": "FAKE", "algo": "plain"}}')
        self.assertNotIn("FAKE", result)
        self.assertIn("[REDACTED]", result)

    def test_a_secret_nested_one_level_deeper_as_a_json_array_is_redacted(self):
        result = redact_secrets('{"api_key": ["FAKE", "also-fake"]}')
        self.assertNotIn("FAKE", result)
        self.assertIn("[REDACTED]", result)

    def test_a_truncated_pem_block_with_no_end_marker_is_still_redacted(self):
        # V07-010: a real log excerpt cut off mid-key (a bounded log
        # tail, a crash right after the BEGIN line) has no END marker
        # at all - _PEM_BLOCK_RE's own BEGIN...END match requires both,
        # so the entire block, key material included, used to pass
        # through completely unredacted.
        text = "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAKCAQEA1234567890abcdef\n"
        result = redact_secrets(text)
        self.assertNotIn("MIIEpQIBAAKCAQEA1234567890abcdef", result)
        self.assertIn("[REDACTED]", result)
        self.assertIn("before", result)

    def test_a_complete_pem_block_is_unaffected_by_the_truncated_case(self):
        text = "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEpQIBAAKCAQEA1234567890abcdef\n-----END RSA PRIVATE KEY-----\nafter"
        result = redact_secrets(text)
        self.assertNotIn("MIIEpQIBAAKCAQEA1234567890abcdef", result)
        self.assertIn("before", result)
        self.assertIn("after", result)


class RedactLinesTests(unittest.TestCase):
    def test_redacts_a_secret_on_its_own_line(self):
        lines = ["clean line", "SECRET=oops", "another clean line"]
        result = redact_lines(lines)
        self.assertEqual(result[0], "clean line")
        self.assertEqual(result[1], "SECRET=[REDACTED]")
        self.assertEqual(result[2], "another clean line")

    def test_empty_list_returns_empty_list(self):
        self.assertEqual(redact_lines([]), [])


if __name__ == "__main__":
    unittest.main()
