import pytest

from qwenpaw.app.sealed_agents.models import SealedAgentRecord, SealedReleaseRecord
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.service import SealedAgentService, SealedAgentReleaseError


def test_delete_retains_assets_and_security_boundary(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    service = SealedAgentService(root=tmp_path, registry=registry, trusted_signers={})
    release = SealedReleaseRecord(release_id='r1', version='1.0', content_digest='digest', signer_id='signer')
    registry.upsert_agent(SealedAgentRecord(agent_id='old', name='Old', releases=[release], active_release_id='r1'))
    with pytest.raises(SealedAgentReleaseError, match='停用'):
        service.delete('old', actor='admin')
    service.disable('old')
    asset = tmp_path / 'retained-package.zip'
    asset.write_bytes(b'package')
    service.delete('old', actor='admin')
    assert service.list_agents() == []
    assert registry.is_sealed('old')
    stored = SealedAgentRegistry(tmp_path).get_agent('old')
    assert stored.deleted_at is not None
    assert stored.deleted_by == 'admin'
    assert not stored.enabled
    assert stored.releases == [release]
    assert asset.read_bytes() == b'package'
    with pytest.raises(SealedAgentReleaseError):
        service.enable('old')
    with pytest.raises(SealedAgentReleaseError):
        service.activate('old', 'r1')
