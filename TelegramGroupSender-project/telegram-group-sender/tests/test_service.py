from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from tgs.service import Service


@pytest.mark.asyncio
async def test_send_requires_current_permissions():
    service = Service(None)
    service.inspect = AsyncMock(return_value={'allowed': False})
    service.client = SimpleNamespace(send_message=AsyncMock())
    with pytest.raises(ValueError): await service.send({'link': ('public:test', 'test', False)}, 'text')
    service.client.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_plaintext_and_no_retry():
    service = Service(None)
    service.inspect = AsyncMock(return_value={'allowed': True, 'entity': 'group'})
    service.client = SimpleNamespace(send_message=AsyncMock(side_effect=TimeoutError))
    with pytest.raises(TimeoutError): await service.send({'link': ()}, '🦊\n**literal**')
    service.client.send_message.assert_awaited_once_with('group', '🦊\n**literal**', parse_mode=None, link_preview=False)


def test_flood_blocks_requests():
    service = Service(None)
    service.flood(60)
    with pytest.raises(ValueError): service.ready()

@pytest.mark.parametrize('admin,default_ban,user_ban,expected', [
    (False, False, False, True), (False, True, False, False),
    (False, False, True, False), (True, True, True, True)])
def test_post_rights(admin, default_ban, user_ban, expected):
    from tgs.service import can_post
    entity = SimpleNamespace(default_banned_rights=SimpleNamespace(send_plain=default_ban))
    permissions = SimpleNamespace(is_admin=admin, is_creator=False,
        participant=SimpleNamespace(banned_rights=SimpleNamespace(send_messages=user_ban)))
    assert can_post(entity, permissions) == expected
