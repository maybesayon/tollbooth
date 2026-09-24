import pytest
from cryptography.fernet import Fernet

from tollbooth.security import (
    DecryptionError,
    SecretBox,
    generate_virtual_key,
    hash_virtual_key,
    tokens_match,
)


def test_generated_keys_are_unique_and_hash_consistently() -> None:
    a, b = generate_virtual_key(), generate_virtual_key()
    assert a.plaintext != b.plaintext
    assert a.plaintext.startswith("tb_")
    assert a.key_hash == hash_virtual_key(a.plaintext)
    assert a.plaintext.startswith(a.display_prefix)
    assert len(a.display_prefix) == 11


def test_secret_box_round_trip_and_rotation() -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    token = SecretBox(old).encrypt("sk-real")
    assert "sk-real" not in token
    assert SecretBox(f"{new},{old}").decrypt(token) == "sk-real"
    with pytest.raises(DecryptionError):
        SecretBox(new).decrypt(token)


def test_secret_box_requires_a_key() -> None:
    with pytest.raises(ValueError, match="at least one"):
        SecretBox(" , ")


def test_tokens_match() -> None:
    assert tokens_match("abc", "abc")
    assert not tokens_match("abc", "abd")
