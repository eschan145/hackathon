"""OS credential vault helper — actual secrets never touch SQLite.

Per ARCHITECTURE.md section 8 ("Auth state"): OAuth tokens/secrets for
integrations are stored via the OS credential vault (Windows Credential
Manager / DPAPI via `keyring`, Keychain on macOS, Secret Service on
Linux). `MemoryStore.set_credential_ref` / `get_credential_ref` only ever
persist an opaque `ref_key` string in SQLite (the `credentials_ref`
table) — never the secret value itself.

`keyring` is imported lazily/optionally: if it's not installed, this
degrades to a process-local in-memory dict so demos still run, with a
clear TODO to install `keyring` for real secret persistence.
"""

from __future__ import annotations

from typing import Optional

try:
    import keyring  # type: ignore

    _HAS_KEYRING = True
except ImportError:  # pragma: no cover - optional dependency
    keyring = None  # type: ignore
    _HAS_KEYRING = False

# TODO(keyring): `pip install keyring` for real OS-vault-backed secret
# storage. Without it, secrets only live in this process's memory and are
# lost on restart (fine for a demo, not for production).

# NOTE: kept as-is (not renamed to "orchestratr") because it is the actual
# keyring service namespace used to look up already-stored OS-vault secrets;
# changing it would orphan any credentials a user has already saved.
_SERVICE_NAMESPACE = "nvidia_hackathon_assistant"


class CredentialVault:
    """Thin wrapper over `keyring.set_password`/`get_password`.

    `ref_key` is the opaque identifier stored alongside `service` in
    MemoryStore's `credentials_ref` table (e.g. "gmail:default"). The
    actual secret (OAuth token, API key, etc.) is stored/retrieved here,
    keyed by (namespace, ref_key), and never written to SQLite.
    """

    def __init__(self, namespace: str = _SERVICE_NAMESPACE) -> None:
        self._namespace = namespace
        self._fallback: dict[str, str] = {}

    def store_secret(self, ref_key: str, secret: str) -> None:
        if _HAS_KEYRING:
            keyring.set_password(self._namespace, ref_key, secret)
        else:
            self._fallback[ref_key] = secret

    def get_secret(self, ref_key: str) -> Optional[str]:
        if _HAS_KEYRING:
            return keyring.get_password(self._namespace, ref_key)
        return self._fallback.get(ref_key)

    def delete_secret(self, ref_key: str) -> None:
        if _HAS_KEYRING:
            try:
                keyring.delete_password(self._namespace, ref_key)
            except Exception:
                pass
        else:
            self._fallback.pop(ref_key, None)
