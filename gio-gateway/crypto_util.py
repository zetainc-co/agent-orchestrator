"""
AES-256-GCM decryption compatible with NestJS encryption.util.ts.
Format: base64(salt[32] + iv[16] + tag[16] + ciphertext)
"""
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.backends import default_backend

SALT_LENGTH = 32
IV_LENGTH   = 16
TAG_LENGTH  = 16
KEY_LENGTH  = 32


def _derive_key(secret: str, salt: bytes) -> bytes:
    """scryptSync equivalent: scrypt(secret, salt, key_length)"""
    kdf = Scrypt(salt=salt, length=KEY_LENGTH, n=16384, r=8, p=1, backend=default_backend())
    return kdf.derive(secret.encode())


def decrypt(encrypted_base64: str, secret: str) -> str:
    """Decrypt a value encrypted by the NestJS encrypt() function."""
    data = base64.b64decode(encrypted_base64)

    salt       = data[:SALT_LENGTH]
    iv         = data[SALT_LENGTH : SALT_LENGTH + IV_LENGTH]
    tag        = data[SALT_LENGTH + IV_LENGTH : SALT_LENGTH + IV_LENGTH + TAG_LENGTH]
    ciphertext = data[SALT_LENGTH + IV_LENGTH + TAG_LENGTH :]

    key = _derive_key(secret, salt)

    # AESGCM expects ciphertext + tag concatenated
    aesgcm    = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    return plaintext.decode("utf-8")
