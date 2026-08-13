"""Token metadata: build the JSON, and turn it into a `metadataUri`.

``PartyToken`` stores one immutable string, ``metadataUri``, and every pools.fun
front end reads the token's identity from whatever it points at. Three forms are
in use on-chain today, and this module can produce all three:

* ``ipfs://<cid>`` — what the reference launch used.
* ``https://…`` — any host you control.
* ``data:application/json;base64,…`` — the whole JSON inlined in calldata. One
  live launch does exactly this.

**`PINATA_JWT` is optional and must stay that way.** A launch with no token image
needs no secret, no account, and no network round trip beyond the chain itself:
the metadata JSON goes inline as a data URI. Pinata is required only for the one
thing that genuinely cannot be inlined — an image, which is far too large for
calldata.

The one hard rule here is that failures are loud. If a caller asks for an image
and Pinata is not configured, this raises. It never quietly launches an
image-less token, because the token's identity is immutable the moment the
transaction lands and there is no second chance to attach the picture.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .chains import ENV_PINATA_JWT, pinata_jwt

PINATA_API = "https://api.pinata.cloud"
PINATA_GATEWAY = "https://gateway.pinata.cloud/ipfs/"
USER_AGENT = "poolsdotfun-token-launcher/1.0"

# Pinata's own limit is far higher, but a token logo has no business being large,
# and catching it here beats a slow upload that fails at the far end.
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Inline metadata is paid for in calldata gas on every launch, forever. A logo URL
# plus a sentence of description fits easily; anything past this is a sign the
# caller meant to pin instead.
MAX_INLINE_URI_BYTES = 8 * 1024

_IMAGE_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".avif": "image/avif",
}

# Magic-byte sniffing, because AgentOS webchat attachments routinely arrive with a
# generic or missing extension and the suffix alone would mislabel them.
_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"<svg", "image/svg+xml"),
    (b"<?xml", "image/svg+xml"),
]


class PinataError(RuntimeError):
    """Anything that went wrong talking to Pinata."""


def pinata_configured() -> bool:
    return pinata_jwt() is not None


def require_pinata_jwt(reason: str) -> str:
    """The JWT, or a refusal that says exactly how to fix it.

    Called only from paths that truly need Pinata. The message names the AgentOS
    setup action and the escape hatch, because "PINATA_JWT is not set" on its own
    leaves the user guessing whether the skill is broken or just unconfigured.
    """
    jwt = pinata_jwt()
    if not jwt:
        raise PinataError(
            f"{reason} needs Pinata, but {ENV_PINATA_JWT} is not set.\n"
            f"  Either set it in the agent environment "
            f"(AgentOS: Skills page -> Set {ENV_PINATA_JWT}),\n"
            f"  or drop --image and launch without a token image,\n"
            f"  or pass --metadata-uri <uri> if you have already hosted the metadata."
        )
    return jwt


def _post(url: str, body: bytes, headers: dict[str, str], timeout: int = 120) -> dict:
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        if exc.code in (401, 403):
            raise PinataError(
                f"Pinata rejected the credentials (HTTP {exc.code}). Check {ENV_PINATA_JWT} "
                f"is a valid JWT — not an API key or secret. {detail}"
            ) from exc
        raise PinataError(f"Pinata request failed: HTTP {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PinataError(f"Pinata unreachable: {exc}") from exc


def verify_pinata_auth(jwt: str) -> None:
    """Probe the JWT before uploading anything.

    A bad token surfaces here in one cheap request rather than after a multi-megabyte
    upload, and — more importantly — before the launch plan is built around an image
    that was never going to pin.
    """
    request = urllib.request.Request(
        f"{PINATA_API}/data/testAuthentication",
        headers={"authorization": f"Bearer {jwt}", "user-agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise PinataError(
            f"{ENV_PINATA_JWT} was rejected by Pinata (HTTP {exc.code}). It must be a JWT "
            "from Pinata -> API Keys, not the API key or secret."
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PinataError(f"Pinata unreachable: {exc}") from exc


def _guess_mime(path: Path, head: bytes) -> str:
    for magic, mime in _MAGIC:
        if head.startswith(magic):
            return mime
    suffix = path.suffix.lower()
    if suffix in _IMAGE_MIME:
        return _IMAGE_MIME[suffix]
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _multipart(fields: dict[str, str], filename: str, mime: str,
               payload: bytes) -> tuple[bytes, str]:
    """Hand-rolled multipart/form-data.

    The skill deliberately has no third-party dependencies (it targets the system
    python that ships with macOS), so there is no `requests` to lean on and
    urllib cannot build this itself.
    """
    boundary = "----poolsfun" + base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
    # A boundary that appeared inside the payload would truncate the upload. With
    # 96 random bits that is not going to happen by chance, but the check is one
    # line and the failure it prevents is a silently corrupt logo.
    if boundary.encode() in payload:
        raise PinataError("could not frame the upload; retry")
    out = bytearray()
    for key, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'content-disposition: form-data; name="{key}"\r\n\r\n'.encode()
        out += value.encode() + b"\r\n"
    out += f"--{boundary}\r\n".encode()
    out += (
        f'content-disposition: form-data; name="file"; filename="{filename}"\r\n'
    ).encode()
    out += f"content-type: {mime}\r\n\r\n".encode()
    out += payload + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def pin_file(path: str | Path, jwt: str, *, name: str | None = None) -> str:
    """Pin a local file to IPFS. Returns the CID."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise PinataError(f"image not found: {file_path}")
    payload = file_path.read_bytes()
    if not payload:
        raise PinataError(f"image is empty: {file_path}")
    if len(payload) > MAX_IMAGE_BYTES:
        raise PinataError(
            f"image is {len(payload) / 1048576:.1f} MB, over the "
            f"{MAX_IMAGE_BYTES // 1048576} MB limit. Resize it first."
        )
    mime = _guess_mime(file_path, payload[:16])
    if not mime.startswith("image/"):
        raise PinataError(
            f"{file_path.name} does not look like an image (detected {mime}). "
            "Pass a png/jpg/gif/webp/svg."
        )
    body, content_type = _multipart(
        {"pinataMetadata": json.dumps({"name": name or file_path.name})},
        file_path.name, mime, payload,
    )
    result = _post(
        f"{PINATA_API}/pinning/pinFileToIPFS", body,
        {"authorization": f"Bearer {jwt}", "content-type": content_type,
         "user-agent": USER_AGENT},
    )
    cid = result.get("IpfsHash")
    if not cid:
        raise PinataError(f"Pinata returned no IpfsHash: {result}")
    return str(cid)


def pin_json(obj: dict, jwt: str, *, name: str = "metadata.json") -> str:
    """Pin a JSON document to IPFS. Returns the CID."""
    body = json.dumps(
        {"pinataContent": obj, "pinataMetadata": {"name": name}},
        separators=(",", ":"),
    ).encode()
    result = _post(
        f"{PINATA_API}/pinning/pinJSONToIPFS", body,
        {"authorization": f"Bearer {jwt}", "content-type": "application/json",
         "user-agent": USER_AGENT},
    )
    cid = result.get("IpfsHash")
    if not cid:
        raise PinataError(f"Pinata returned no IpfsHash: {result}")
    return str(cid)


def build_metadata(name: str, symbol: str, *, description: str | None = None,
                   image: str | None = None, website: str | None = None,
                   twitter: str | None = None) -> dict:
    """The metadata document, shaped like the ones already on-chain.

    Field order and names match what pools.fun itself writes, so existing readers
    parse it without special-casing. Empty fields are omitted rather than sent as
    empty strings — a null logo renders worse than an absent one.
    """
    doc: dict[str, Any] = {"name": name, "symbol": symbol}
    if description:
        doc["description"] = description
    if image:
        doc["image"] = image
    if website:
        doc["website"] = website
    if twitter:
        doc["twitter"] = twitter
    return doc


def to_data_uri(doc: dict) -> str:
    """Inline the metadata as a base64 data URI — no hosting, no secret."""
    raw = json.dumps(doc, separators=(",", ":")).encode()
    uri = "data:application/json;base64," + base64.b64encode(raw).decode()
    if len(uri) > MAX_INLINE_URI_BYTES:
        raise PinataError(
            f"inline metadata is {len(uri)} bytes, over the {MAX_INLINE_URI_BYTES} byte "
            f"limit — it would make every launch needlessly expensive. Shorten "
            f"--description, or set {ENV_PINATA_JWT} to pin it instead."
        )
    return uri


def resolve_metadata_uri(*, name: str, symbol: str, metadata_uri: str | None = None,
                         image: str | None = None, description: str | None = None,
                         website: str | None = None, twitter: str | None = None,
                         pin: bool = False) -> tuple[str, dict | None, str]:
    """Produce the `metadataUri` for a launch.

    Returns ``(uri, document_or_None, how)`` where ``how`` is a short phrase for
    the plan block so the user can see which path ran.

    Precedence, highest first:

    1. ``metadata_uri`` — pass-through, never touches Pinata.
    2. ``image`` — pin the image, then pin the JSON. Requires PINATA_JWT.
    3. ``pin`` — pin the JSON only. Requires PINATA_JWT.
    4. otherwise — inline data URI. No secret, no network.
    """
    if metadata_uri:
        uri = metadata_uri.strip()
        if not (uri.startswith("ipfs://") or uri.startswith("https://")
                or uri.startswith("data:")):
            raise PinataError(
                f"--metadata-uri must start with ipfs://, https:// or data: (got {uri[:32]!r})"
            )
        return uri, None, "supplied"

    if image:
        jwt = require_pinata_jwt("attaching a token image")
        verify_pinata_auth(jwt)
        image_cid = pin_file(image, jwt, name=f"{symbol} logo")
        # Use the HTTPS gateway form for `image`, matching what pools.fun writes:
        # every wallet and explorer renders it, whereas ipfs:// needs a resolver.
        doc = build_metadata(name, symbol, description=description,
                             image=PINATA_GATEWAY + image_cid,
                             website=website, twitter=twitter)
        cid = pin_json(doc, jwt, name=f"{symbol} metadata")
        return f"ipfs://{cid}", doc, "image pinned via Pinata"

    doc = build_metadata(name, symbol, description=description,
                         website=website, twitter=twitter)
    if pin:
        jwt = require_pinata_jwt("--pin-metadata")
        verify_pinata_auth(jwt)
        cid = pin_json(doc, jwt, name=f"{symbol} metadata")
        return f"ipfs://{cid}", doc, "pinned via Pinata"

    return to_data_uri(doc), doc, "inline (no image)"
