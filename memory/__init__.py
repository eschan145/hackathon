"""Memory subsystem: unified MemoryStore facade (SQLite + vector store).

See ARCHITECTURE.md section 8 for the design. `MemoryStore` implements
the `core.interfaces.Memory` protocol (`save_task`, `get_similar_workflow`)
plus the wider preferences/contacts/app-usage/credential-ref surface.
"""

from .credential_vault import CredentialVault
from .store import MemoryStore
from .vector_store import EpisodicMemory

__all__ = ["MemoryStore", "EpisodicMemory", "CredentialVault"]
