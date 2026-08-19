from app.collectors.awin_mapper import AwinAdvertiserConfig


def load_awin_advertisers(source_config: dict) -> list[AwinAdvertiserConfig]:
    advertisers: list[AwinAdvertiserConfig] = []
    for item in source_config.get("advertisers") or []:
        if not isinstance(item, dict):
            continue
        try:
            advertiser_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(item.get("name") or "").strip() or str(advertiser_id)
        display_name = str(item.get("display_name") or name).strip() or name
        advertisers.append(
            AwinAdvertiserConfig(
                id=advertiser_id,
                name=name,
                display_name=display_name,
                enabled=bool(item.get("enabled", True)),
            )
        )
    return advertisers
