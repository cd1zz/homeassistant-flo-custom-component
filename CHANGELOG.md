# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-08-10

### Changed
- **api.py — new Moen login flow.** Moen migrated Flo accounts onto the
  Cognito-backed "Smart Water" gateway (`api.prod.iot.moen.com`). The old
  `api-gw.meetflo.com` OAuth2 *password* grant no longer authenticates
  migrated accounts, which left the integration unable to log in. Login now
  posts the username/password to the Moen gateway
  (`POST https://api.prod.iot.moen.com/v1/oauth2/token`,
  `grant_type=client_credentials`, new app `client_id`) and uses the Bearer
  token it returns. The legacy Flo v2 data/control endpoints (valve,
  systemMode, health test, presence, consumption, device/location reads) are
  unchanged and still accept this token, so entities and services behave
  exactly as before.
- Token refresh now targets the same Moen gateway
  (`grant_type=refresh_token`).

### Added
- The Moen token no longer embeds the Flo user id, so after login the client
  resolves it from the account email (mirrors the app's
  `getUserDetails(email)`), then continues to use the existing
  `/v2/users/{id}?expand=locations` discovery path.
- Every Flo request now sends `User-Agent: Flo-Android`, matching the app
  (some endpoints reject an unknown User-Agent).

### Notes
- Credentials/flow were extracted from the Moen Android app
  (`com.moen.smartwater` v3.56.x). These are Moen-controlled values and may
  change; if login breaks again, the client id / token URL are the first
  things to re-check.

## [1.1.1] - 2026-04-30

### Fixed
- **api.py**: short-circuit on `204 No Content` (or empty body) before
  calling `resp.json()`. Mode-change endpoints such as
  `POST /locations/{id}/systemMode` return 204 with no body; the previous
  unconditional `resp.json()` raised `"Attempt to decode JSON with
  unexpected mimetype"` even though the call had succeeded, causing HA
  to log a spurious failure and delaying sensor refresh until the next
  poll. Picks up a fix from the dormant
  `claude/document-repo-purpose-CFeRt` branch (follow-up to issue #2).

## [1.1.0] - 2026-04-30

### Added
- **Reauthentication flow**: when the Flo API returns a persistent 401 (e.g.,
  refresh token revoked because the user changed their Moen password),
  Home Assistant now prompts for the new password instead of leaving entities
  "unavailable" forever until restart. Implemented via the standard
  `async_step_reauth` / `async_step_reauth_confirm` config-flow steps.

### Changed
- **Coordinator architecture**: replaced per-device polling coordinators with a
  single `FloLocationDataUpdateCoordinator` per location. Each cycle now issues
  one `presence/me`, one `water/consumption`, and N parallel `devices/{id}`
  requests instead of `1 + 3·N` serialized-then-stampeded requests. For a
  household with 13 leak detectors + 1 shutoff this drops Moen API traffic
  from ~60,000 requests/day to ~22,000 and removes the per-minute burst that
  could trip rate limits.
- Per-device coordinators are now passive proxies that subscribe to the
  location coordinator. Public properties unchanged — entity layer is untouched.

### Fixed
- **services.yaml**: `set_sleep_mode` UI options (`120/1440/4320`) no longer
  contradict the voluptuous schema (`60..720` step 60). Selecting a value from
  the UI now actually validates.
- **entity.py**: when Moen omits `macAddress` (e.g., unprovisioned device), the
  `unique_id` falls back to `{device.id}_{entity_type}` instead of producing
  collision-prone `_<entity_type>` ids. `DeviceInfo.connections` is omitted
  rather than emitting an empty `(mac, "")` tuple that could merge unrelated
  devices in the device registry.
- **api.py**: 401 responses on regular requests now trigger a token refresh
  and one retry; persistent 401s raise `FloAuthError` so the coordinator can
  prompt the user to reauthenticate (previously silently became "unavailable"
  forever until HA restart).
- **api.py**: token-refresh `KeyError` on a malformed Moen response now falls
  through to a full re-auth instead of crashing the coordinator.
- **__init__.py**: `async_unload_entry` now shuts down all coordinators, so
  reload no longer leaks listeners or background tasks.
- **__init__.py**: first-refresh runs concurrently across locations.

### Removed
- `orjson` listed as a manifest requirement (it ships with HA Core; the
  refresh-failure stack trace now uses stdlib `json.JSONDecodeError`).

## [1.0.0] - 2025-11-03

### Added
- **OAuth2 authentication support** for Moen Flo API
- New `api.py` module with complete OAuth2 client implementation
- Automatic access token refresh (5 minutes before expiry)
- Support for OAuth2 refresh tokens
- Bearer token authentication format
- Comprehensive error handling for authentication failures

### Changed
- **BREAKING**: Updated authentication flow from simple auth to OAuth2 password grant
- Updated API endpoints to use new OAuth2 token endpoint
- Removed dependency on `aioflo` library (now self-contained)
- Updated manifest.json to remove external dependencies
- Modified coordinator to use new API client methods
- Updated config flow for OAuth2 authentication
- Changed switch valve control to use new API methods

### Fixed
- **Critical**: Fixed "500 Internal Server Error" when accessing user info endpoint
- **Critical**: Fixed "401 Unauthorized" errors with v2 API endpoints
- Fixed token format incompatibility (now uses "Bearer" prefix)
- Fixed integration setup failures due to API changes

### Technical Details
- OAuth2 client credentials: `3baec26f-0e8b-4e1d-84b0-e178f05ea0a5` (extracted from Moen mobile app)
- Access token lifetime: 24 hours (86400 seconds)
- Refresh token lifetime: ~92 years
- Token refresh trigger: 5 minutes before expiry
- API base URL: `https://api-gw.meetflo.com/api`

### Migration Notes
- Users must remove the built-in Flo integration before installing this custom component
- Re-authentication required (username/password)
- All entities and services remain the same
- Configuration is preserved

### Known Limitations
- Tokens not persisted across HA restarts (re-authentication required)
- Client credentials are hardcoded (will need update if Moen rotates them)
- No backward compatibility with old aioflo library

## [Unreleased]

### Planned
- Token persistence across restarts
- HACS default repository submission
- Integration tests for OAuth2 flow
- Automated token refresh testing
- Support for multiple Flo accounts

---

## Version Numbering

- **Major version** (X.0.0): Breaking changes or major new features
- **Minor version** (1.X.0): New features, backward compatible
- **Patch version** (1.0.X): Bug fixes, backward compatible
