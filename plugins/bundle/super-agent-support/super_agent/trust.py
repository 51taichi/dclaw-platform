"""Publisher trust policy for Super Agent packages."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SuperExpertTrustStore:
    official_signer_ids: frozenset[str]

    def is_official(self, signer_id: str) -> bool:
        return signer_id in self.official_signer_ids
