# Test plan

What has been checked, and what hasn't. The automated suite (`uv run pytest`) covers everything below except the last section. Every test runs against real RSA keys and a real local HTTP server standing in for the platform. Nothing is mocked. The live Brightspace items need a sandbox tenant we don't have yet.

## Automated suite

- [x] `uv run pytest` passes with no warnings. Warnings fail the run.
- [x] `uv run pyright` in strict mode is clean across `src`, `tests`, and `examples`

## Key management

- [x] `uv run lti1p3-generate-keypair` writes a 2048-bit or larger RSA key pair, the private key with mode 0600, and prints the matching JWK
- [x] `--help` prints usage. A missing or blank `--kid`, `--bits` under 2048, a non-numeric `--bits`, or an unknown argument exits 1 with a message on stderr
- [x] `buildJwks` builds a JWKS from a `Registration`'s keys, old rotated-out keys included, and refuses a public key that is not RSA or not PEM

## Built-in file cache

- [x] `FileCache` stores, reads, replaces, deletes, and clears values. A second `FileCache` on the same directory sees them
- [x] `FileCache` creates its directory when it is missing
- [x] Expired items read as missing, for integer and `timedelta` TTLs, zero and negative included
- [x] `removeExpired()` deletes only expired items and reports how many
- [x] A cache file that is not valid JSON, or not a cache record, counts as a miss
- [x] `examples/setupExample.py` works on a fresh home directory and creates `keys/` and `config.json`
- [x] The example tool runs login, launch, AGS score, and NRPS roster against the simulator on the library's `FileCache`. A replayed launch is rejected. `tests/test_examples.py` drives this.

## JWKS fetching

- [x] `JwksFetcher` fetches and parses a JWKS from the fixture server, sending `Accept: application/json`
- [x] The document is cached and not fetched again within the TTL. After the TTL it is fetched again
- [x] `JwtValidator` rejects a token whose `kid` is missing or not in the JWKS as malformed
- [x] Non-RSA entries, and RSA entries declaring an algorithm other than RS256, are dropped before any key is built from them
- [x] A JWKS with no acceptable keys, an unparsable RSA key, a non-200 status, a non-JSON body, or no `keys` array raises `ServiceException`

## JWT and launch validation

- [x] A fresh id_token signed by the fixture platform validates end to end
- [x] An expired id_token is rejected
- [x] An id_token with an `iat` in the future is rejected as not yet valid
- [x] A wrong signature is rejected
- [x] An `iss` that doesn't match is rejected. A trailing slash counts as a mismatch
- [x] `aud` as a string is checked against the client_id
- [x] `aud` as an array must contain the client_id and must come with a matching `azp`
- [x] A missing `aud` is rejected
- [x] A replayed `nonce` is rejected. So is a missing one
- [x] `alg:none` and any other algorithm but RS256 are rejected before verification starts
- [x] A token without three segments, with an undecodable header, or with no `alg` in the header is rejected as malformed
- [x] A tampered, mismatched, unknown, or replayed `state` is rejected
- [x] A `target_link_uri` or `deployment_id` that differs between login initiation and launch is rejected
- [x] A `deployment_id` the registration doesn't know is rejected, even when login initiation didn't name one
- [x] An anonymous launch, with `sub` missing or null, is accepted. `subject` is `None`
- [x] A tampered payload under the original signature is rejected
- [x] No PyJWT exception type escapes the public API. Each is remapped to `InvalidLaunchException`, with the PyJWT exception kept as `__cause__`
- [x] Clock-skew leeway: a token well inside the window passes, one well past it fails. The exact instant isn't tested; it would race the wall clock
- [x] Plain-http platform URLs, and a `target_link_uri` or `redirect_uri` on a remote host over plain http, are rejected. Loopback (127.0.0.1, localhost, ::1) is allowed for local work

The PHP suite also checked that `JWT::$leeway`, a global in firebase/php-jwt, was restored after validation. PyJWT takes leeway per call, so there is nothing to restore and no test here.

## OIDC login and resource link launch

- [x] `LoginInitiationHandler` builds the redirect to the platform's auth endpoint with the right parameters, a fresh state and nonce, and a cached login-state record. It appends correctly when the auth URL already has a query string
- [x] Login initiation, then the auth redirect, then the launch, all against the fixture server, yields an `LtiResourceLinkRequest`
- [x] An unexpected `message_type` or an unsupported LTI `version` is rejected
- [x] A missing `resource_link` claim is rejected
- [x] `custom`, `context`, and `tool_platform` claims come through intact
- [x] A launch without `state` or `id_token` raises `InvalidLoginInitiationException`
- [x] A registration that disappears between login and launch raises `RegistrationNotFoundException`

## Assignment and Grades Service (AGS)

- [x] The access token comes from a client_credentials JWT-bearer grant against the fixture token endpoint and is cached. The client assertion is a real signed JWT, verified against the tool's own JWKS
- [x] The client assertion's `aud` defaults to the platform token URL and uses `platformAudience` when the registration sets one
- [x] The token cache honors `expires_in` minus the safety margin, assumes an hour when `expires_in` is missing, and is keyed by scope set
- [x] Line item create, read, update, and delete against the fixture AGS endpoint, with the AGS media types in `Accept` and `Content-Type` and a Bearer token
- [x] Score publish against the fixture AGS endpoint carries the `activityProgress` and `gradingProgress` values, the score media type, and a Bearer token
- [x] Result read against the fixture AGS endpoint
- [x] A non-2xx status, a non-JSON body, or a list response that isn't an array raises `ServiceException`

## Names and Role Provisioning Service (NRPS)

- [x] Roster fetch against the fixture NRPS endpoint with the membership container `Accept` type
- [x] `Link: rel="next"` pagination is followed. Checked across a real two-page sequence. A `Link` header without `rel="next"` stops the walk
- [x] A non-200 status, a non-JSON body, or a response without a `members` array raises `ServiceException`

## Deep Linking

- [x] `LtiDeepLinkingRequest` parses `deep_linking_settings` and rejects a launch without it
- [x] `LtiDeepLinkingResponse` signs with the active key and puts its `kid` in the header. `renderFormPost` posts a field named `JWT`, not `id_token`, to `deep_link_return_url`
- [x] The whole round trip against the fixture server: login, launch dispatch, response JWT, form post, verification on the platform side
- [x] `LaunchValidator` dispatches on `message_type` to `LtiResourceLinkRequest` or `LtiDeepLinkingRequest`
- [x] The response JWT reverses `iss` and `aud` relative to the launch: the tool signs, and `aud` is the platform's issuer
- [x] The `data` claim is echoed back when the request had one and left out when it didn't
- [x] The example tool: Deep Linking launch, selection form, signed response, and the simulator verifying it against the tool's JWKS. `tests/test_examples.py` drives this.

## Live Brightspace

Blocked until we have a sandbox tenant.

- [ ] Register this tool in a Brightspace sandbox
- [ ] A real login and launch from a Brightspace course
- [ ] A real AGS score passback that shows up in the Brightspace gradebook
- [ ] A real NRPS roster fetch from a Brightspace course
- [ ] A real Deep Linking content selection from a Brightspace course
