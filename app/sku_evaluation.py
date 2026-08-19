import re
import unicodedata
from decimal import Decimal, InvalidOperation

from app.sku_models import SkuMetrics, SkuStatus, SkuVariant

_COLOR_TRANSLATIONS = {
    "black": "Preto",
    "preto": "Preto",
    "white": "Branco",
    "branco": "Branco",
    "blue": "Azul",
    "azul": "Azul",
    "red": "Vermelho",
    "vermelho": "Vermelho",
    "green": "Verde",
    "verde": "Verde",
    "gray": "Cinza",
    "grey": "Cinza",
    "cinza": "Cinza",
    "gold": "Dourado",
    "dourado": "Dourado",
    "silver": "Prata",
    "prata": "Prata",
    "pink": "Rosa",
    "rosa": "Rosa",
    "purple": "Roxo",
    "roxo": "Roxo",
}

_ACCESSORY_TERMS = (
    "accessory only",
    "only accessory",
    "somente acessorio",
    "apenas acessorio",
    "without product",
    "sem produto",
    "case only",
    "capa apenas",
    "cable only",
    "cabo apenas",
    "charger only",
    "carregador apenas",
)
_ACCESSORY_ONLY_WORDS = {
    "accessory",
    "acessorio",
    "case",
    "capa",
    "cable",
    "cabo",
    "charger",
    "carregador",
}
_LENGTH_PATTERN = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(?:m|metro|metros|meter|meters)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_VALUES = {
    "color",
    "cor",
    "size",
    "tamanho",
    "default",
    "padrao",
    "standard",
}
_COSMETIC_PROPERTY_NAMES = {
    "color",
    "colour",
    "cor",
}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def _format_length(value: str) -> str:
    try:
        number = Decimal(value.replace(",", "."))
    except (InvalidOperation, ValueError):
        return f"{value} m"
    formatted = format(number.normalize(), "f").replace(".", ",")
    return f"{formatted} m"


def _split_variation_tokens(value: str) -> tuple[str, list[str], list[str]]:
    lengths = [
        _format_length(match.group(1))
        for match in _LENGTH_PATTERN.finditer(value)
    ]
    without_lengths = _LENGTH_PATTERN.sub(" ", value)
    words = without_lengths.split()
    material_words: list[str] = []
    colors: list[str] = []
    for word in words:
        token = re.sub(r"^[^\w]+|[^\w]+$", "", word)
        translated = _COLOR_TRANSLATIONS.get(_normalize(token))
        if translated:
            if translated not in colors:
                colors.append(translated)
            continue
        material_words.append(word)
    material = " ".join(material_words)
    material = re.sub(r"\s+", " ", material).strip(" -•/")
    return material, colors, lengths


def _derive_variation_identity(sku: SkuVariant) -> tuple[str, str, str | None]:
    material_parts: list[str] = []
    variation_parts: list[str] = []
    grouping_dimension: str | None = None
    for property_item in sku.properties:
        if _normalize(property_item.value) in _PLACEHOLDER_VALUES:
            continue
        material, colors, lengths = _split_variation_tokens(property_item.value)
        property_name = _normalize(property_item.name)
        if (
            property_name in _COSMETIC_PROPERTY_NAMES
            and not colors
            and not lengths
        ):
            variation = property_item.value.strip()
            if variation and variation not in variation_parts:
                variation_parts.append(variation)
            grouping_dimension = grouping_dimension or "appearance"
            continue
        if material and material not in material_parts:
            material_parts.append(material)
        for variation in colors + lengths:
            if variation not in variation_parts:
                variation_parts.append(variation)
        if lengths:
            grouping_dimension = "length"

    material_signature = " • ".join(material_parts) or "__base__"
    variation_label = ", ".join(variation_parts)
    return material_signature, variation_label, grouping_dimension


def derive_variation_identity(sku: SkuVariant) -> tuple[str, str]:
    material_signature, variation_label, _ = _derive_variation_identity(sku)
    return material_signature, variation_label


def _looks_like_accessory(label: str, product_title: str) -> bool:
    normalized_label = _normalize(label)
    normalized_title = _normalize(product_title)
    for term in _ACCESSORY_TERMS:
        normalized_term = _normalize(term)
        if normalized_term in normalized_label and normalized_term not in normalized_title:
            return True
    label_words = set(normalized_label.split())
    title_words = set(normalized_title.split())
    accessory_words = label_words & _ACCESSORY_ONLY_WORDS
    if accessory_words and not accessory_words & title_words:
        return True
    return False


def evaluate_skus(
    skus: list[SkuVariant],
    product_title: str,
    metrics: SkuMetrics | None = None,
) -> list[SkuVariant]:
    multiple_skus = len(skus) > 1
    for sku in skus:
        (
            material_signature,
            cosmetic_label,
            grouping_dimension,
        ) = _derive_variation_identity(sku)
        sku.material_signature = material_signature
        sku.cosmetic_label = cosmetic_label
        sku.grouping_dimension = grouping_dimension

        if not sku.sku_id:
            sku.sku_status = SkuStatus.REJECTED
            sku.rejection_reason = "sku_id_ausente"
        elif sku.effective_price is None:
            sku.sku_status = SkuStatus.REJECTED
            sku.rejection_reason = "preco_ausente_ou_invalido"
        elif _looks_like_accessory(sku.variation_label, product_title):
            sku.sku_status = SkuStatus.REJECTED
            sku.rejection_reason = "variacao_aparenta_ser_acessorio"
        elif sku.rejection_reason == "sku_properties_invalid" and multiple_skus:
            sku.sku_status = SkuStatus.UNRESOLVED
        elif (
            multiple_skus
            and material_signature == "__base__"
            and not cosmetic_label
        ):
            sku.sku_status = SkuStatus.UNRESOLVED
            sku.rejection_reason = "variacao_sem_atributos_significativos"
        elif not sku.properties and multiple_skus:
            sku.sku_status = SkuStatus.UNRESOLVED
            sku.rejection_reason = "atributos_ausentes_em_produto_multisku"
        else:
            sku.sku_status = SkuStatus.RESOLVED
            sku.rejection_reason = None

        if metrics is None:
            continue
        if sku.sku_status == SkuStatus.RESOLVED:
            metrics.resolved_skus += 1
        elif sku.sku_status == SkuStatus.UNRESOLVED:
            metrics.unresolved_skus += 1
        else:
            metrics.rejected_skus += 1
    return skus
