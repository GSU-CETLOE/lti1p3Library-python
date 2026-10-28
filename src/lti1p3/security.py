"""RSA key generation, the tool's JWKS, fetching a platform's JWKS, and id_token validation."""

import base64
import json
from typing import Any

import httpx
import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from lti1p3.cache import CacheInterface, buildCacheKey
from lti1p3.claims import jsonList, jsonObject
from lti1p3.exceptions import (
    InvalidLaunchException,
    InvalidLaunchReason,
    InvalidRegistrationException,
    KeyGenerationException,
    ServiceException,
)
from lti1p3.registration import Registration, ToolKeyPair

ACCEPTED_ALGORITHM = "RS256"
DEFAULT_KEY_BITS = 2048

type Jwk = dict[str, str]
type JwksDocument = dict[str, list[Jwk]]
type KeySet = dict[str, jwt.PyJWK]


def generateKeyPair(kid: str, keyBits: int = DEFAULT_KEY_BITS) -> ToolKeyPair:
    """Generate a fresh RSA key pair for signing outbound tool JWTs, as PKCS#8 and SubjectPublicKeyInfo PEM.

    Backs the generate-keypair command and the test fixtures; the library
    itself never generates keys at runtime.
    """
    try:
        privateKey = rsa.generate_private_key(public_exponent=65537, key_size=keyBits)
    except ValueError as error:
        raise KeyGenerationException(f"Failed to generate RSA key pair: {error}") from error

    privatePem = privateKey.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    publicPem = privateKey.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return ToolKeyPair(kid, privatePem.decode("ascii"), publicPem.decode("ascii"))


def buildJwks(registration: Registration) -> JwksDocument:
    """Build the tool's public JWKS document (RFC 7517) for publishing at its JWKS URL.

    Includes every key, not just the active signing one, so the platform can
    keep verifying tokens signed with a key that has since been rotated out.
    """
    return {"keys": [buildJwk(keyPair) for keyPair in registration.toolKeyPairs]}


def buildJwk(keyPair: ToolKeyPair) -> Jwk:
    """Build the JWK entry for one key pair, for example to print a newly generated key."""
    try:
        publicKey = serialization.load_pem_public_key(keyPair.publicKey.encode("utf-8"))
    except (ValueError, TypeError, UnsupportedAlgorithm) as error:
        raise InvalidRegistrationException(f'Could not parse public key for kid "{keyPair.kid}".') from error

    if not isinstance(publicKey, rsa.RSAPublicKey):
        raise InvalidRegistrationException(f'Public key for kid "{keyPair.kid}" is not a valid RSA key.')

    numbers = publicKey.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": ACCEPTED_ALGORITHM,
        "kid": keyPair.kid,
        "n": _base64UrlEncodeInteger(numbers.n),
        "e": _base64UrlEncodeInteger(numbers.e),
    }


def _base64UrlEncodeInteger(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class JwksFetcher:
    """Fetches and caches a platform's published JWKS as a kid-to-key mapping.

    Only RSA/RS256 entries are accepted. A fetched JWKS is external input,
    and a JWT library will happily build a symmetric HS256 key from a JWK
    entry that declares one. Those are filtered out before a key is ever
    built, rather than relying on the caller alone.
    """

    DEFAULT_CACHE_TTL_SECONDS = 3600

    def __init__(self, httpClient: httpx.Client, cache: CacheInterface, cacheTtlSeconds: int = DEFAULT_CACHE_TTL_SECONDS):
        self.httpClient = httpClient
        self.cache = cache
        self.cacheTtlSeconds = cacheTtlSeconds

    def fetch(self, jwksUrl: str) -> KeySet:
        """Return the platform's acceptable keys by kid, from cache when fresh."""
        document = self._fetchDocument(jwksUrl)
        entries = jsonList(document.get("keys")) or []
        acceptable = [entry for entry in map(jsonObject, entries) if entry is not None and self._isAcceptable(entry)]

        if not acceptable:
            raise ServiceException(f'JWKS from "{jwksUrl}" did not contain any supported RSA/RS256 keys.')

        keySet: KeySet = {}
        for entry in acceptable:
            try:
                key = jwt.PyJWK(entry, algorithm=ACCEPTED_ALGORITHM)
            except jwt.PyJWTError as error:
                raise ServiceException(f'JWKS from "{jwksUrl}" contains a key that could not be parsed.') from error
            if isinstance(key.key_id, str):
                keySet[key.key_id] = key

        return keySet

    def _fetchDocument(self, jwksUrl: str) -> dict[str, Any]:
        """The raw JWKS document, from cache when fresh, otherwise fetched over HTTP and cached."""
        cacheKey = buildCacheKey("jwks", jwksUrl)
        cached = jsonObject(self.cache.get(cacheKey))
        if cached is not None:
            return cached

        response = self.httpClient.get(jwksUrl, headers={"Accept": "application/json"})
        if response.status_code != 200:
            raise ServiceException(f'Fetching JWKS from "{jwksUrl}" failed with HTTP status {response.status_code}.')

        try:
            decoded = jsonObject(json.loads(response.text))
        except ValueError as error:
            raise ServiceException(f'JWKS response from "{jwksUrl}" was not valid JSON.') from error

        if decoded is None or jsonList(decoded.get("keys")) is None:
            raise ServiceException(f'JWKS response from "{jwksUrl}" did not contain a "keys" array.')

        self.cache.set(cacheKey, decoded, self.cacheTtlSeconds)
        return decoded

    @staticmethod
    def _isAcceptable(entry: dict[str, Any]) -> bool:
        if entry.get("kty") != "RSA":
            return False
        algorithm = entry.get("alg")
        return algorithm is None or algorithm == ACCEPTED_ALGORITHM


class JwtValidator:
    """Validates an inbound id_token against a Registration.

    Checks the header algorithm, the signature via the platform's JWKS, iss,
    aud and azp, exp and iat with clock-skew leeway, and nonce replay. Out of
    scope here, and handled by LaunchValidator: binding the token's
    target_link_uri and deployment_id to what was recorded at login, and the
    `state` round trip, since those are launch-flow concerns rather than
    properties of the token itself.
    """

    DEFAULT_CLOCK_SKEW_LEEWAY_SECONDS = 60
    DEFAULT_NONCE_TTL_SECONDS = 3600

    def __init__(
        self,
        jwksFetcher: JwksFetcher,
        nonceCache: CacheInterface,
        clockSkewLeewaySeconds: int = DEFAULT_CLOCK_SKEW_LEEWAY_SECONDS,
        nonceTtlSeconds: int = DEFAULT_NONCE_TTL_SECONDS,
    ):
        self.jwksFetcher = jwksFetcher
        self.nonceCache = nonceCache
        self.clockSkewLeewaySeconds = clockSkewLeewaySeconds
        self.nonceTtlSeconds = nonceTtlSeconds

    def validate(self, idToken: str, registration: Registration) -> dict[str, Any]:
        """Verify the token and return its claims, raising InvalidLaunchException on any failure."""
        header = self._decodeHeader(idToken)
        self._assertAllowedAlgorithm(header.get("alg"))

        keySet = self.jwksFetcher.fetch(registration.platformJwksUrl)
        claims = self._decodeToken(idToken, header.get("kid"), keySet)

        self._assertIssuer(claims, registration)
        self._assertAudience(claims, registration)
        self._assertNonceNotReplayed(claims)

        return claims

    @staticmethod
    def _decodeHeader(idToken: str) -> dict[str, Any]:
        segments = idToken.split(".")
        if len(segments) != 3:
            raise InvalidLaunchException(InvalidLaunchReason.MalformedToken, "The id_token does not have three segments.")

        try:
            headerJson = base64.urlsafe_b64decode(segments[0] + "=" * (-len(segments[0]) % 4))
            header = jsonObject(json.loads(headerJson))
        except (ValueError, UnicodeDecodeError) as error:
            raise InvalidLaunchException(
                InvalidLaunchReason.MalformedToken, "The id_token header could not be decoded."
            ) from error

        if header is None or not isinstance(header.get("alg"), str):
            raise InvalidLaunchException(
                InvalidLaunchReason.MalformedToken, 'The id_token header does not contain an "alg".'
            )

        return header

    @staticmethod
    def _assertAllowedAlgorithm(algorithm: object) -> None:
        if algorithm != ACCEPTED_ALGORITHM:
            raise InvalidLaunchException(
                InvalidLaunchReason.UnsupportedAlgorithm, f'The id_token uses unsupported algorithm "{algorithm}".'
            )

    def _decodeToken(self, idToken: str, kid: object, keySet: KeySet) -> dict[str, Any]:
        if not isinstance(kid, str) or kid not in keySet:
            raise InvalidLaunchException(
                InvalidLaunchReason.MalformedToken, 'The id_token could not be verified: "kid" is missing or unknown.'
            )

        try:
            return jwt.decode(
                idToken,
                keySet[kid],
                algorithms=[ACCEPTED_ALGORITHM],
                leeway=self.clockSkewLeewaySeconds,
                # iss, aud, and azp are checked below with LTI-specific rules; sub may be absent (anonymous launch).
                options={"verify_aud": False, "verify_iss": False, "verify_sub": False, "verify_jti": False},
            )
        except jwt.ExpiredSignatureError as error:
            raise InvalidLaunchException(InvalidLaunchReason.Expired, "The id_token has expired.") from error
        except jwt.ImmatureSignatureError as error:
            raise InvalidLaunchException(InvalidLaunchReason.NotYetValid, "The id_token is not yet valid.") from error
        except jwt.InvalidSignatureError as error:
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidSignature, "The id_token signature is invalid."
            ) from error
        except jwt.InvalidTokenError as error:
            raise InvalidLaunchException(
                InvalidLaunchReason.MalformedToken, f"The id_token could not be verified: {error}"
            ) from error

    @staticmethod
    def _assertIssuer(claims: dict[str, Any], registration: Registration) -> None:
        if claims.get("iss") != registration.issuer:
            raise InvalidLaunchException(
                InvalidLaunchReason.InvalidIssuer, 'The id_token "iss" does not match the registered issuer.'
            )

    @staticmethod
    def _assertAudience(claims: dict[str, Any], registration: Registration) -> None:
        audience = claims.get("aud")

        if isinstance(audience, str):
            if audience != registration.clientId:
                raise InvalidLaunchException(
                    InvalidLaunchReason.InvalidAudience, 'The id_token "aud" does not match the registered client_id.'
                )
            return

        audienceList = jsonList(audience)
        if audienceList is not None:
            if registration.clientId not in audienceList:
                raise InvalidLaunchException(
                    InvalidLaunchReason.InvalidAudience,
                    'The id_token "aud" array does not contain the registered client_id.',
                )
            if claims.get("azp") != registration.clientId:
                raise InvalidLaunchException(
                    InvalidLaunchReason.InvalidAudience,
                    'The id_token "aud" is an array but "azp" does not match the registered client_id.',
                )
            return

        raise InvalidLaunchException(
            InvalidLaunchReason.InvalidAudience, 'The id_token "aud" claim is missing or has an unexpected type.'
        )

    def _assertNonceNotReplayed(self, claims: dict[str, Any]) -> None:
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or nonce == "":
            raise InvalidLaunchException(
                InvalidLaunchReason.MissingNonce, 'The id_token does not contain a "nonce" claim.'
            )

        cacheKey = buildCacheKey("nonce", nonce)
        if self.nonceCache.has(cacheKey):
            raise InvalidLaunchException(
                InvalidLaunchReason.ReplayedNonce, 'The id_token "nonce" has already been used.'
            )

        self.nonceCache.set(cacheKey, True, self.nonceTtlSeconds)
