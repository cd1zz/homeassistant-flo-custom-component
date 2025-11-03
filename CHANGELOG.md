# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
