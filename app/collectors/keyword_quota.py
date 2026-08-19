def keyword_quotas(keyword_count: int, max_items: int) -> list[int]:
    if keyword_count <= 0 or max_items <= 0:
        return []
    base = max_items // keyword_count
    remainder = max_items % keyword_count
    return [base + (1 if index < remainder else 0) for index in range(keyword_count)]
