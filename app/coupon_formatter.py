from datetime import datetime

from app.coupon_lifecycle import (
    filter_active_or_future_coupons,
    is_campaign_scheduled,
    now_in_timezone,
)
from app.coupon_render import (
    build_benefit_line,
    build_campaign_coupon_lines,
    build_condition_lines,
    build_limit_line,
)
from app.models import Coupon, CouponCampaign, FormattedMessage, MessageAction

EVENT_ACTION_TEXT = "🔥 Acessar evento"
COUPON_ACTION_TEXT = "🎟️ Acessar cupom"


def _format_datetime(value: datetime) -> str:
    return value.strftime("%d/%m/%Y às %H:%M")


def _format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def _is_midnight(value: datetime) -> bool:
    return value.hour == 0 and value.minute == 0 and value.second == 0


def _title_line(campaign: CouponCampaign, coupon_count: int) -> str:
    emoji = "🔥" if coupon_count > 1 else "🎟️"
    return f"{emoji} {campaign.title}"


def _schedule_block(campaign: CouponCampaign) -> list[str]:
    if campaign.start_at is None:
        return []
    if _is_midnight(campaign.start_at):
        return ["Começa à meia-noite."]
    return [f"Começa em {_format_datetime(campaign.start_at)}."]


def _validity_block(campaign: CouponCampaign, now: datetime) -> list[str]:
    if campaign.end_at is None:
        return []
    end_at = campaign.end_at
    if end_at.date() == now.date():
        return [f"Válido até hoje às {_format_time(end_at)}."]
    return [f"Válido até {_format_datetime(end_at)}."]


def _single_coupon_block(coupon: Coupon) -> list[str]:
    lines: list[str] = []
    benefit = build_benefit_line(coupon)
    if benefit:
        lines.append(benefit)
    limit = build_limit_line(coupon)
    if limit:
        lines.append(limit)
    if coupon.code:
        lines.append("")
        lines.append(f"Código: {coupon.code}")
    conditions = build_condition_lines(coupon)
    if conditions:
        lines.append("")
        lines.extend(conditions)
    return lines


def _multi_coupon_block(coupons: list[Coupon]) -> list[str]:
    lines = ["Cupons do evento:"]
    for coupon in coupons:
        lines.append("")
        lines.extend(build_campaign_coupon_lines(coupon))
    return lines


def _resolve_primary_url(campaign: CouponCampaign) -> str | None:
    if campaign.affiliate_url:
        return campaign.affiliate_url
    if campaign.campaign_url:
        return campaign.campaign_url
    for coupon in campaign.coupons:
        url = coupon.affiliate_url or coupon.coupon_url
        if url:
            return url
    return None


def _build_actions(campaign: CouponCampaign, coupon_count: int) -> list[MessageAction]:
    url = _resolve_primary_url(campaign)
    if not url:
        return []
    text = EVENT_ACTION_TEXT if coupon_count > 1 else COUPON_ACTION_TEXT
    return [MessageAction(text=text, url=url, action_type="campaign")]


def _join_blocks(blocks: list[list[str]]) -> str:
    rendered = ["\n".join(block) for block in blocks if block]
    return "\n\n".join(rendered).strip()


def format_coupon_campaign(
    campaign: CouponCampaign,
    now: datetime | None = None,
) -> FormattedMessage:
    current = now or now_in_timezone()
    coupons = filter_active_or_future_coupons(campaign.coupons, current)
    coupon_count = len(coupons)

    blocks: list[list[str]] = [[_title_line(campaign, coupon_count)]]

    if campaign.description:
        blocks.append([campaign.description])

    if is_campaign_scheduled(campaign, current):
        blocks.append(_schedule_block(campaign))
    elif coupon_count == 1:
        blocks.append(_single_coupon_block(coupons[0]))
    elif coupon_count > 1:
        blocks.append(_multi_coupon_block(coupons))

    blocks.append(_validity_block(campaign, current))

    text = _join_blocks(blocks)
    actions = _build_actions(campaign, coupon_count)

    return FormattedMessage(
        text=text,
        image_url=campaign.image_url or None,
        actions=actions,
    )
