import asyncio

def can_post(entity, permissions):
    if permissions.is_admin or permissions.is_creator:
        return True
    rights = [getattr(entity, "default_banned_rights", None),
              getattr(permissions.participant, "banned_rights", None)]
    return not any(r and any(getattr(r, flag, False) for flag in
                           ("view_messages", "send_messages", "send_plain")) for r in rights)

import time
from telethon import TelegramClient, functions, types, errors
from telethon.sessions import StringSession


class Service:
    def __init__(self, vault):
        self.vault = vault
        self.client = None
        self.phone = None
        self.phone_hash = None
        self.blocked_until = 0

    def ready(self):
        remaining = int(self.blocked_until - time.monotonic()) + 1
        if remaining > 0:
            raise ValueError(f'Ограничение Telegram: подождите {remaining} с.')

    async def connect(self, api_id, api_hash):
        if self.client:
            await self.client.disconnect()
        self.client = TelegramClient(StringSession(self.vault.get('session') or ''), api_id, api_hash,
                                     flood_sleep_threshold=0, request_retries=0, receive_updates=False)
        await self.client.connect()
        return await self.client.is_user_authorized()

    async def request_code(self, phone):
        self.ready()
        self.phone = phone
        sent = await self.client.send_code_request(phone)
        self.phone_hash = sent.phone_code_hash

    async def login(self, code=None, password=None):
        self.ready()
        if password is not None:
            await self.client.sign_in(password=password)
        else:
            await self.client.sign_in(self.phone, code, phone_code_hash=self.phone_hash)
        self.vault.set('session', self.client.session.save())
        self.phone_hash = None

    async def inspect(self, link, join=False):
        self.ready()
        key, token, private = link
        if private:
            invite = await self.client(functions.messages.CheckChatInviteRequest(token))
            if isinstance(invite, types.ChatInviteAlready):
                entity = invite.chat
            elif not join:
                return dict(link=link, title=getattr(invite, 'title', 'Приватная группа'), member=False, allowed=False)
            else:
                updates = await self.client(functions.messages.ImportChatInviteRequest(token))
                entity = updates.chats[0]
        else:
            entity = await self.client.get_entity(token)
            if not isinstance(entity, (types.Chat, types.Channel)) or getattr(entity, 'broadcast', False):
                raise ValueError('Ссылка должна вести в группу, а не в канал или личный чат.')
            if join:
                await self.client(functions.channels.JoinChannelRequest(entity))
        if getattr(entity, 'broadcast', False):
            raise ValueError('Публикация в каналах не поддерживается.')
        try:
            permissions = await self.client.get_permissions(entity, 'me')
            member = (not getattr(entity, 'left', False) and not permissions.has_left
                      and not getattr(permissions.participant, 'left', False))
        except errors.UserNotParticipantError:
            member, permissions = False, None
        allowed = bool(member and permissions and can_post(entity, permissions))
        return dict(link=link, title=entity.title, member=member, allowed=allowed, entity=entity, peer=entity.id)

    async def send(self, group, message):
        self.ready()
        # Recheck membership and permissions immediately before each explicit delivery.
        current = await self.inspect(group['link'])
        if not current['allowed']:
            raise ValueError('Нет участия или права на публикацию.')
        sent = await self.client.send_message(current['entity'], message, parse_mode=None, link_preview=False)
        return sent.id

    def flood(self, seconds):
        self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)


class Worker:
    """Single persistent asyncio loop in a background thread."""
    def __init__(self):
        import threading
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()

    def submit(self, coroutine):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)
