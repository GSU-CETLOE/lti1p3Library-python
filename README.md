# lti1p3

A Python library for the tool side of LTI 1.3 Advantage. It handles the OIDC login and launch, Deep Linking 2.0, the Assignment and Grades Service (AGS) 2.0, and the Names and Role Provisioning Service (NRPS) 2.0. It works with any web framework, or none.

It is a port of the PHP library in the sibling `lti1p3Library-php` repository and keeps the same shape: the same classes, the same validation rules, and the same test coverage. It was built against D2L Brightspace, but it follows the 1EdTech specs, so it should work with any LMS that follows them too.

Every feature is covered by an automated test suite. The tests use real cryptography and a real local HTTP server, with no mocks. The library has not been run against a live Brightspace tenant yet. [TESTPLAN.md](TESTPLAN.md) lists what has been verified and what is still waiting on a sandbox.

## Requirements

- Python 3.13 or newer.
- [uv](https://docs.astral.sh/uv/) for package and script management.

The library depends on three packages, which uv installs for you: `httpx` for HTTP calls to the platform, `pyjwt` for signing and verifying JWTs, and `cryptography` for RSA keys.

## Setup

Install uv if you don't have it:

```bash
# macOS (Homebrew)
brew install uv

# or the official installer
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then, from this directory:

```bash
uv sync
```

These commands cover day-to-day development:

```bash
uv run pytest        # run the test suite
uv run pyright       # static type checking (strict mode)
```

Both must come back clean. The test suite treats warnings as failures.

## What your application provides

The library has no hard dependency on a web framework, a database, or a cache server. You hand it these pieces:

| You provide | The library uses it for |
|---|---|
| An `httpx.Client` | Calls to the platform: JWKS fetches, token requests, AGS, and NRPS |
| A class that implements `RegistrationRepositoryInterface` | Looking up platform registrations in your own database |
| A cache that implements `CacheInterface` (optional, one is included) | Short-lived data such as login state and access tokens. See [Caching](#caching). |

Requests and responses are plain values. A handler takes a mapping of the request's parameters and returns an `HttpResponse` with a status code, headers, and a text body. Your framework turns those into its own request and response objects. The [examples](examples/) do this with the standard library's HTTP server.

Inbound tokens must use RS256. The JWKS fetcher drops any key that isn't RSA with RS256 before it can be used to check a signature.

## Usage

The steps below go in order. Each code sample reuses variables from the earlier ones.

### 1. Generate a signing key

```bash
uv run lti1p3-generate-keypair --kid=2026-01-key-1
```

This writes a private and public key to `working/keys` and prints a JWK. Your tool publishes that JWK at its JWKS URL in step 4.

### 2. Create a cache

```python
from lti1p3 import FileCache

cache = FileCache("working/cache")
```

That is the whole setup. The directory is created if it doesn't exist. Pass this same `cache` to every class below that asks for one.

If your application already has Redis, Memcached, or another cache, wrap it in the five methods of `CacheInterface` and pass that instead. [Caching](#caching) explains when you should.

### 3. Implement `RegistrationRepositoryInterface`

```python
from lti1p3 import Registration


class DatabaseRegistrationRepository:
    def findForLoginInitiation(self, issuer: str, clientId: str | None) -> Registration | None:
        # Look up your stored platform registration by issuer (and client_id if given).
        # Return None if nothing matches or the match is ambiguous. Never raise.
        ...

    def findForLaunch(self, issuer: str, clientId: str, deploymentId: str) -> Registration | None:
        # The same lookup, also scoped to one deployment_id.
        ...
```

`RegistrationRepositoryInterface` is a `Protocol`, so your class does not need to inherit from it. It only needs these two methods.

### 4. Serve your JWKS endpoint

```python
from lti1p3 import buildJwks

jwks = buildJwks(registration)  # {"keys": [...]}
# Return this as the JSON body of your tool's JWKS URL.
```

### 5. Handle the OIDC login request

```python
from lti1p3 import LoginInitiationHandler

handler = LoginInitiationHandler(registrationRepository, cache)
response = handler.handle(requestParams, "https://your-tool.example.com/lti/launch")
# response.statusCode is 302 and response.headers["Location"] is the platform's auth endpoint.
```

`requestParams` is a mapping of the request's parameters: the query string for a GET, or the form body for a POST. The platform may send either.

### 6. Handle the launch

The platform POSTs back to your redirect URI. Validate that request:

```python
import httpx

from lti1p3 import JwksFetcher, JwtValidator, LaunchValidator, LtiDeepLinkingRequest, LtiResourceLinkRequest

httpClient = httpx.Client(timeout=10)
jwksFetcher = JwksFetcher(httpClient, cache)
jwtValidator = JwtValidator(jwksFetcher, cache)
validator = LaunchValidator(registrationRepository, cache, jwtValidator)

message = validator.validate(formParams)  # raises InvalidLaunchException on any failure

if isinstance(message, LtiResourceLinkRequest):
    ...  # message.subject, .roles, .resourceLink, .context, .custom, ...
elif isinstance(message, LtiDeepLinkingRequest):
    ...  # message.deepLinkingSettings.deepLinkReturnUrl, .acceptTypes, ...
```

`formParams` is the parsed POST body, which carries `state` and `id_token`.

### 7. Call the platform (AGS and NRPS)

```python
from lti1p3 import AccessTokenService, ActivityProgress, AssignmentsGradesService, GradingProgress, NamesRoleService, Score

accessTokenService = AccessTokenService(httpClient, cache)
ags = AssignmentsGradesService(httpClient, accessTokenService)
nrps = NamesRoleService(httpClient, accessTokenService)

# endpoint.lineItemUrl is only set when exactly one line item belongs to
# this resource link. Otherwise create one first with
# ags.createLineItem(registration, endpoint, LineItem(...)).
endpoint = message.agsEndpoint()
if endpoint is not None and endpoint.lineItemUrl is not None and message.subject is not None:
    ags.publishScore(
        registration,
        endpoint.lineItemUrl,
        Score(
            userId=message.subject,
            activityProgress=ActivityProgress.Completed,
            gradingProgress=GradingProgress.FullyGraded,
            scoreGiven=8.5,
            scoreMaximum=10.0,
        ),
    )

nrpsEndpoint = message.nrpsEndpoint()
if nrpsEndpoint is not None:
    roster = nrps.getMembers(registration, nrpsEndpoint)  # list[Member], follows pagination for you
```

If these calls come back `invalid_client` while launches work fine, read [Access-token audience](#access-token-audience).

### 8. Respond to a Deep Linking request

```python
from lti1p3 import LtiDeepLinkingResponse, LtiResourceLinkContentItem, renderFormPost

response = LtiDeepLinkingResponse(
    registration,
    message.deploymentId,
    message.rawClaims["iss"],  # the platform's issuer, from the original request
    [LtiResourceLinkContentItem(url="https://your-tool.example.com/launch/42", title="Selected item")],
    data=message.deepLinkingSettings.data,
)

return renderFormPost(
    message.deepLinkingSettings.deepLinkReturnUrl,
    {"JWT": response.toJwt()},  # the spec names this field "JWT", not "id_token"
)
```

`renderFormPost` returns an `HttpResponse` whose body is an auto-submitting HTML form.

## Caching

The library caches four things. You don't have to manage any of them yourself.

| What | Kept for | Why |
|---|---|---|
| The platform's JWKS (public keys) | 1 hour | So a launch doesn't fetch the keys every time |
| Login state | 5 minutes, and deleted as soon as the launch uses it | Ties a launch to the login request that started it |
| Nonces | 1 hour | Rejects an id_token that is sent a second time |
| Service access tokens | The token's lifetime minus 60 seconds | So AGS and NRPS calls don't request a new token each time |

To change a duration, pass it to the constructor: `cacheTtlSeconds` on `JwksFetcher`, `stateTtlSeconds` on `LoginInitiationHandler`, or `nonceTtlSeconds` on `JwtValidator`. For example:

```python
jwksFetcher = JwksFetcher(httpClient, cache, cacheTtlSeconds=600)
```

### Using the included `FileCache`

`FileCache` keeps one JSON file per cached item in the directory you give it. It needs no server and no configuration, which makes it a good fit for a tool that runs on a single web server.

Three things to know:

1. Keep the directory private. Put it outside your web root and make sure only your application can write to it. `FileCache` creates it with mode `0700`.
2. Clean it up on a schedule. Each launch leaves one small nonce file behind, and nothing reads it again unless someone replays the launch. Run this once a day from cron or your scheduler:

   ```python
   from lti1p3 import FileCache

   removed = FileCache("working/cache").removeExpired()
   ```

3. Don't use it across several web servers unless they share the directory. The login request and the launch are two separate HTTP requests. If they land on different servers with different disks, the launch won't find its login state and will be rejected.

### Using your own cache

Any object with these five methods works. Pass it wherever the steps above pass `cache`:

```python
class CacheInterface(Protocol):
    def get(self, key: str, default: object = None) -> object: ...
    def set(self, key: str, value: object, ttl: int | timedelta | None = None) -> bool: ...
    def delete(self, key: str) -> bool: ...
    def has(self, key: str) -> bool: ...
    def clear(self) -> bool: ...
```

Choose this when you run more than one web server, or when your application already has a cache you'd like to reuse. Values are JSON-shaped: strings, numbers, booleans, lists, and dicts.

The cache has to keep data between requests. A plain in-memory dict will not work in production, because the launch arrives in a different request than the login that stored its state.

Every key the library writes starts with `lti1p3_` and contains only letters, digits, and underscores, hyphens, or dots, so the keys are valid in any backend and are easy to tell apart from your application's own.

## Access-token audience

When the library requests a service access token, it signs a client assertion. The `aud` claim of that assertion defaults to the platform's token endpoint, which is what the 1EdTech Security Framework specifies.

Some platforms want a different value. Brightspace is one: its registration page publishes a "Brightspace OAuth2 Audience" (`https://api.brightspace.com/auth/token`) that is not the token URL you POST to. Canvas does the same and wants `https://canvas.instructure.com/login/oauth2/token` whatever the region-specific token URL is.

This is an easy mistake to miss. Launches never touch the token endpoint, so they keep working while every AGS and NRPS call fails with `invalid_client`. To set the audience, pass the optional last argument to `Registration`:

```python
registration = Registration(
    issuer,
    clientId,
    deploymentIds,
    platformAuthenticationLoginUrl,
    platformAuthenticationTokenUrl,
    platformJwksUrl,
    toolKeyPairs,
    platformAudience="https://canvas.instructure.com/login/oauth2/token",  # optional
)
```

Only the `aud` claim changes. The token request still goes to `platformAuthenticationTokenUrl`. `registration.accessTokenAudience()` returns the value in effect, and `registration.platformAudience` is `None` when you haven't set one.

The audience doesn't have to be a URL, because some platforms use an opaque identifier, so it skips the HTTPS check that the endpoint URLs get. It can't be an empty string.

## Command-line helper

### `lti1p3-generate-keypair`

Generates a new RSA signing key pair for your tool and prints the matching JWK. Run it once when you set up the tool, and again whenever you rotate keys. The library never calls it at runtime.

```bash
uv run lti1p3-generate-keypair --kid=<kid> [--bits=2048] [--out-dir=working/keys]
uv run lti1p3-generate-keypair --help
```

For example:

```bash
uv run lti1p3-generate-keypair --kid=2026-01-key-1
uv run lti1p3-generate-keypair --kid=2026-07-key-2 --bits=4096 --out-dir=/etc/my-tool/keys
```

It writes `<kid>.private.pem` (mode `0600`) and `<kid>.public.pem` into `--out-dir`, which defaults to `working/keys` under the current directory, and prints the key's JWK as JSON on stdout. Keep the private key out of version control. Give both PEM files to a `ToolKeyPair` when you build your `Registration`.

When this library is installed as a dependency of your application, the same command is available in that application's environment.

## Examples

The [examples](examples/) directory holds a minimal LTI 1.3 tool built on this library and a platform simulator that stands in for Brightspace, so the whole flow can be clicked through locally. Setup and run them from this directory:

```bash
uv run python examples/setupExample.py
uv run python examples/tool.py        # in one terminal
uv run python examples/simulator.py   # in another
```

Then open http://localhost:8001/ and click "Launch as a resource link" or "Launch as a Deep Linking request". Keys, config, cache files, and the simulator's small JSON gradebook all go under `working/example/`.

The test suite starts both servers as real subprocesses and drives the same flow, so the examples cannot drift from the library.

## Registering this tool with D2L Brightspace

A Brightspace admin or developer registers the tool once per environment, in two steps, through the LE API (`/d2l/api/le/(version)/ltiadvantage/...`).

Step 1 is the tool registration. You provide:

| Field | Value |
|---|---|
| `OpenIDConnectLoginUrl` | Your tool's login endpoint (step 5 above) |
| `KeysetUrl` | Your tool's JWKS URL (step 4 above) |
| `RedirectUrls` | Array of authorized launch and redirect URIs (step 6 above) |

Step 2 is the deployment. It is linked to the registration by `ClientId`, and it sets which user fields Brightspace sends (`SendUserFirstName`, `SendUserEmail`, `SendD2LUserId`, and so on).

Brightspace then returns the values you need to build your `Registration` object:

| Brightspace field | `Registration` constructor argument |
|---|---|
| `BrightspaceIssuer` | `issuer` |
| The `ClientId` from your deployment | `clientId` |
| `BrightspaceOIDCAuthenticationEndpoint` | `platformAuthenticationLoginUrl` |
| `BrightspaceOAuth2AccessTokenUrl` | `platformAuthenticationTokenUrl` |
| `BrightspaceKeysetUrl` | `platformJwksUrl` |
| `BrightspaceOAuth2Audience` | `platformAudience` (required for Brightspace, because it is not the token URL) |

Brightspace's JWKS endpoint usually looks like `https://<your-subdomain>.brightspace.com/d2l/.well-known/jwks`.

A deployment's `EnabledExtensions` array says which Advantage services are active for it. This library supports AGS, Deep Linking, and NRPS. Recent Brightspace versions always enable Deep Linking, whatever the request asks for.

The OIDC login URL and the redirect URIs must use HTTPS. Brightspace rejects `http://` at registration time, and this library applies the same rule when you construct a `Registration`. The one exception is loopback addresses, which the library's own local test fixtures use.

## How this differs from the PHP library

The public API keeps the PHP names, so the PHP README's steps map one to one. The differences are where PHP standards had no Python equivalent:

| PHP | Python |
|---|---|
| PSR-18 client plus PSR-17 factories | An `httpx.Client` |
| PSR-16 `CacheInterface` | A five-method `CacheInterface` Protocol; `FileCache` stores JSON, not serialized PHP |
| PSR-7 `ServerRequestInterface` | A mapping of request parameters |
| PSR-7 `ResponseInterface` | An `HttpResponse` value (status code, headers, body) |
| `firebase/php-jwt` | PyJWT with `cryptography` |
| `JwksBuilder`, `KeyPairGenerator`, `FormPostRenderer` classes | The functions `buildJwks`, `buildJwk`, `generateKeyPair`, and `renderFormPost` |
| `toArray()` | `toDict()` |
| One file per class | One module per area: `cache`, `claims`, `messages`, `deepLinking`, `oidcLogin`, `security`, `ags`, `nrps`, and so on |

Everything is importable from the `lti1p3` package directly.

## Known limitations

- No end-to-end testing against a live Brightspace tenant yet. That needs a sandbox; see [TESTPLAN.md](TESTPLAN.md).
- `AssignmentsGradesService.listLineItems()` fetches a single page and does not follow `Link` header pagination. NRPS roster fetches do paginate.
- Submission Review and the Platform Notification Service are not implemented in this version.

## License

MIT. See [LICENSE](LICENSE).
