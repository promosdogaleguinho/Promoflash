_MOJIBAKE_MARKERS = ("Ã", "Â")


def fix_mojibake(value: str | None) -> str | None:
    """Corrige UTF-8 lido como Latin-1 de forma conservadora.

    Só altera textos com sinais claros de mojibake (ex.: Ã, Â).
    Textos já válidos permanecem intactos.
    """
    if value is None:
        return None
    if not value:
        return value
    if not any(marker in value for marker in _MOJIBAKE_MARKERS):
        return value

    try:
        fixed = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value

    if not fixed or fixed == value:
        return value
    return fixed
