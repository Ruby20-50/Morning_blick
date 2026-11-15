"""Verification of Nylas webhook signatures (HMAC-SHA256 over the raw body)."""

import hashlib
import hmac


def is_valid_signature(raw_body: bytes, signature: str | None, secret: str) -> bool:
    """True if `signature` (hex, from x-nylas-signature) matches HMAC-SHA256(secret, raw_body)."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    # Compare as bytes: compare_digest raises TypeError on non-ASCII str input,
    # and header values can contain arbitrary characters.
    return hmac.compare_digest(expected.encode(), signature.lower().encode("utf-8", "surrogateescape"))
