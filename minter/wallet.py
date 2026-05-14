import os
from eth_account import Account
from eth_account.messages import encode_defunct
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64


class WalletManager:
    def __init__(self, encryption_key: str):
        self.fernet = self._derive_key(encryption_key) if encryption_key else None

    def _derive_key(self, password: str) -> Fernet:
        salt = b"nft_minter_salt_v1"
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def create_wallet(self) -> tuple:
        acct = Account.create()
        return acct.address, acct.key.hex()

    def encrypt_private_key(self, private_key_hex: str) -> str:
        if not self.fernet:
            return private_key_hex
        return self.fernet.encrypt(private_key_hex.encode()).decode()

    def decrypt_private_key(self, encrypted: str) -> str:
        if not self.fernet:
            return encrypted
        return self.fernet.decrypt(encrypted.encode()).decode()

    def import_private_key(self, private_key_hex: str) -> str:
        acct = Account.from_key(private_key_hex)
        return acct.address

    def sign_transaction(self, private_key_hex: str, tx_dict: dict) -> bytes:
        acct = Account.from_key(private_key_hex)
        return acct.sign_transaction(tx_dict)
