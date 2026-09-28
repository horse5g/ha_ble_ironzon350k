from __future__ import annotations

import unittest

from Crypto.Cipher import AES


class TestCryptoCompatibility(unittest.TestCase):
    """Pin the AES-CBC behavior used by the Tuya BLE transport."""

    def test_aes_128_cbc_known_answer(self) -> None:
        """AES-CBC must continue producing the standard wire bytes."""
        # NIST SP 800-38A F.2.1 AES-128 CBC known-answer vector. The Tuya BLE
        # transport uses this same AES.new(key, AES.MODE_CBC, iv) API directly.
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        ciphertext = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")

        self.assertEqual(
            AES.new(key, AES.MODE_CBC, iv).encrypt(plaintext),
            ciphertext,
        )
        self.assertEqual(
            AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext),
            plaintext,
        )


if __name__ == "__main__":
    unittest.main()
