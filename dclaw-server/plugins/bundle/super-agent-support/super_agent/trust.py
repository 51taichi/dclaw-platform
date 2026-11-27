"""Publisher trust policy for Super Agent packages."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SuperExpertTrustStore:
    official_signer_ids: frozenset[str]
    developer_signer_ids: frozenset[str] = frozenset()

    def is_official(self, signer_id: str) -> bool:
        return signer_id in self.official_signer_ids

    def is_authorized(self, signer_id: str) -> bool:
        return self.is_official(signer_id) or signer_id in self.developer_signer_ids
