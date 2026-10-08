import logging
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

log = logging.getLogger(__name__)


async def is_user_subscribed(bot, user_id: int, channel_username: str) -> bool:
    try:
        member = await bot.get_chat_member(channel_username, user_id)
        accepted = member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
        accepted |= member.status == ChatMemberStatus.RESTRICTED and bool(getattr(member, "is_member", False))
        if not accepted:
            log.info("subscription_denied user=%s", user_id)
        return accepted
    except TelegramAPIError:
        log.warning("subscription_check_unavailable")
        return False


class SubscriptionService:
    """Instagram is a follow link only; add authenticated verification here later."""
    def __init__(self, bot, channel_username):
        self.bot, self.channel_username = bot, channel_username

    async def allowed(self, user_id: int):
        return await is_user_subscribed(self.bot, user_id, self.channel_username)
