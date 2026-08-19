import hashlib
import hmac

SIGN_METHOD_SHA256 = "sha256"
SIGN_METHOD_HMAC = "hmac"
SIGN_METHOD_MD5 = "md5"


def _concatenate_params(params: dict) -> str:
    filtered = {
        key: value
        for key, value in params.items()
        if key != "sign" and value is not None
    }
    ordered_keys = sorted(filtered.keys())
    return "".join(f"{key}{filtered[key]}" for key in ordered_keys)


def build_signature(params: dict, app_secret: str, sign_method: str) -> str:
    concatenated = _concatenate_params(params)
    secret_bytes = app_secret.encode("utf-8")
    method = sign_method.lower()

    if method == SIGN_METHOD_SHA256:
        digest = hmac.new(secret_bytes, concatenated.encode("utf-8"), hashlib.sha256)
        return digest.hexdigest().upper()

    if method == SIGN_METHOD_HMAC:
        digest = hmac.new(secret_bytes, concatenated.encode("utf-8"), hashlib.md5)
        return digest.hexdigest().upper()

    if method == SIGN_METHOD_MD5:
        payload = f"{app_secret}{concatenated}{app_secret}"
        return hashlib.md5(payload.encode("utf-8")).hexdigest().upper()

    raise ValueError(f"Método de assinatura não suportado: {sign_method}")
