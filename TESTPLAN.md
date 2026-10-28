# Test Plan

Manual verification checklist for this library, kept current alongside the automated test suite (`uv run pytest`). Check items off as they are verified against real crypto and a real local fixture platform server, per the no-mocks testing policy. Live-Brightspace end-to-end items are separate and blocked on having a Brightspace sandbox tenant.

## Automated suite

- [x] `uv run pytest` passes with pristine output (warnings are failures)
- [x] `uv run pyright` (strict mode) passes clean over `src`, `tests`, and `examples`

## Key management

- [x] `uv run lti1p3-generate-keypair` produces a valid RSA keypair (2048-bit minimum) and a matching JWK, with the private key written mode 0600
- [x] `--help` prints usage; a missing or blank `--kid`, `--bits` below 2048, a non-numeric `--bits`, and an unknown argument each exit 1 with a message on stderr
- [x] `buildJwks` produces a valid JWKS document from a `Registration`'s key set, including after key rotation (multiple `ToolKeyPair`s), and rejects a public key that is not RSA or not PEM

## Built-in file cache

- [x] `FileCache` stores, reads, replaces, deletes, and clears values, and a second `FileCache` on the same directory sees them
- [x] `FileCache` creates its directory when it is missing
- [x] Expired items read as missing, for integer and `timedelta` TTLs, including zero and negative TTLs
- [x] `removeExpired()` deletes only expired items and reports how many it removed
- [x] A cache file that is not valid JSON, or not a cache record, is treated as a miss
- [x] `examples/setupExample.py` works on a fresh home directory (creates `keys/` and `config.json`)
- [x] Example tool runs login -> launch -> AGS score -> NRPS roster against the simulator using the library's `FileCache`, and a replayed launch is rejected (automated in `tests/test_examples.py`)

## JWKS fetching

- [x] `JwksFetcher` fetches and parses a real JWKS document from the local fixture platform server, sending `Accept: application/json`
- [x] Result is cached and not re-fetched within TTL; re-fetched once the TTL has elapsed
- [x] Unknown or missing `kid` is rejected as a malformed token by `JwtValidator`
- [x] Non-RSA entries, and RSA entries declaring an algorithm other than RS256, are filtered out before a key is ever built from them
- [x] A JWKS with no acceptable keys, an unparsable RSA key, a non-200 status, non-JSON, or no `keys` array raises `ServiceException`

## JWT / launch validation

- [x] Valid, freshly signed id_token from the fixture platform passes validation end to end
- [x] Expired id_token is rejected
- [x] id_token issued in the future (`iat`) is rejected as not yet valid
- [x] Wrong-signature id_token is rejected
- [x] `iss` mismatch (including trailing-slash variants) is rejected
- [x] `aud` as a plain string is validated correctly
- [x] `aud` as an array requires and validates `azp`, and must contain the client_id
- [x] Missing `aud` is rejected
- [x] Replayed `nonce` is rejected; missing `nonce` is rejected
- [x] `alg:none` / unsupported algorithm is rejected before verification is attempted
- [x] Tokens without three segments, with an undecodable header, or with no `alg` in the header are rejected as malformed
- [x] Tampered/mismatched/unknown/replayed `state` is rejected
- [x] `target_link_uri` / `deployment_id` mismatch between login initiation and launch is rejected
- [x] A `deployment_id` the registration does not know is rejected even when login initiation did not name one
- [x] Anonymous launch (missing or null `sub`) is accepted and modeled as `None`, not an error
- [x] Tampered payload under an otherwise-valid original signature is rejected
- [x] PyJWT exception types never escape the public API (always remapped to `InvalidLaunchException`, with the PyJWT exception preserved as `__cause__`)
- [x] Clock-skew leeway boundary: comfortably within the window is accepted, comfortably beyond it is rejected (exact-instant boundary testing avoided; it is inherently racy against wall-clock time)
- [x] Plain-http platform URLs (login/token/JWKS) and `target_link_uri`/`redirect_uri` to a remote host are rejected; loopback (127.0.0.1/localhost/::1) is allowed for local dev/testing
- [ ] (Not applicable) The PHP suite verified that `JWT::$leeway`, a global in firebase/php-jwt, was restored after validation. PyJWT takes leeway per call, so there is no global state to restore.

## OIDC login + core resource link launch

- [x] `LoginInitiationHandler` builds a correct redirect to the platform's auth endpoint (params, state/nonce, cached login-state record), appending to an auth URL that already has a query string
- [x] Full login initiation -> auth redirect -> launch round trip against the fixture server produces a correctly typed `LtiResourceLinkRequest`
- [x] Unexpected `message_type` / unsupported LTI `version` is rejected
- [x] Missing `resource_link` claim is rejected
- [x] `custom`, `context`, and `tool_platform` claims are captured correctly
- [x] Missing `state` or `id_token` on the launch raises `InvalidLoginInitiationException`
- [x] A registration that disappears between login and launch raises `RegistrationNotFoundException`

## Assignment and Grades Service (AGS)

- [x] Access token is requested via client_credentials JWT-bearer grant against the fixture token endpoint and cached (client assertion is a real signed JWT, verified against the tool's own JWKS)
- [x] Client assertion `aud` defaults to the platform token URL, and uses the configured `platformAudience` override when the registration sets one
- [x] Token cache honors `expires_in` minus the safety margin, assumes an hour when `expires_in` is missing, and keys on the scope set
- [x] Line item create/read/update/delete against the fixture AGS endpoint, with the right `Accept` and `Content-Type` media types and a Bearer token
- [x] Score publish against the fixture AGS endpoint (correct `activityProgress`/`gradingProgress` values, score media type, Bearer token sent)
- [x] Result read against the fixture AGS endpoint
- [x] Non-2xx statuses, non-JSON bodies, and non-array list responses raise `ServiceException`

## Names and Role Provisioning Service (NRPS)

- [x] Roster fetch against the fixture NRPS endpoint with the membership container `Accept` type
- [x] Pagination via `Link: rel="next"` header is followed correctly (verified across a real 2-page sequence); a `Link` without `rel="next"` stops
- [x] Non-200 statuses, non-JSON bodies, and responses without a `members` array raise `ServiceException`

## Deep Linking

- [x] `LtiDeepLinkingRequest` parses the `deep_linking_settings` claim correctly and rejects its absence
- [x] `LtiDeepLinkingResponse` signs a JWT with the active key (its `kid` in the header) and `renderFormPost` posts a form field literally named `JWT` (not `id_token`) to `deep_link_return_url`
- [x] Full Deep Linking round trip against the fixture server (login -> launch dispatch -> response JWT -> form post -> platform-side verification)
- [x] `LaunchValidator` dispatches to `LtiResourceLinkRequest` or `LtiDeepLinkingRequest` based on `message_type`
- [x] Response JWT's `iss`/`aud` are correctly reversed relative to the launch (tool signs, aud = platform issuer)
- [x] `data` claim is echoed back when present in the request, omitted when absent
- [x] Example tool: Deep Linking launch -> selection form -> signed response -> simulator verifies it against the tool's JWKS (automated in `tests/test_examples.py`)

## Live Brightspace (blocked on sandbox tenant)

- [ ] Register this tool in a real Brightspace sandbox
- [ ] Real login -> launch round trip from a Brightspace course
- [ ] Real AGS score passback visible in the Brightspace gradebook
- [ ] Real NRPS roster fetch from a Brightspace course
- [ ] Real Deep Linking content selection from a Brightspace course
