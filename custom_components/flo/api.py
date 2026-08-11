"""Flo API client.

Moen migrated Flo accounts onto the "Smart Water" gateway
(``api.prod.iot.moen.com``), which is backed by AWS Cognito. The old
``api-gw.meetflo.com`` password grant no longer authenticates migrated
accounts, so we now log in against the Moen gateway. The gateway issues a
Bearer token that the *legacy* Flo v2 API still accepts, so only the
authentication step changed — the data and control endpoints are unchanged.

Credentials and the flow were extracted from the Moen Android app
(package ``com.moen.smartwater``, v3.56.x).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Moen "Smart Water" gateway login (extracted from the Moen app). The app
# posts username/password with this odd ``grant_type`` to the Cognito-backed
# gateway and gets back a Bearer token it then uses against the Flo API too.
MOEN_TOKEN_URL = "https://api.prod.iot.moen.com/v1/oauth2/token"
MOEN_CLIENT_ID = "6qn9pep31dglq6ed4fvlq6rp5t"
MOEN_GRANT_TYPE = "client_credentials"

# Flo data/control API. Still live and unchanged; it accepts the Moen token.
API_BASE = "https://api-gw.meetflo.com/api"
API_V2_BASE = f"{API_BASE}/v2"

# The Moen app sends this on the Flo endpoints; some reject a missing/unknown
# User-Agent, so we mirror it on every Flo request.
USER_AGENT = "Flo-Android"


class FloAuthError(HomeAssistantError):
    """Authentication error."""


class FloRequestError(HomeAssistantError):
    """Request error."""


class FloAPI:
    """Flo API client using OAuth2 authentication."""

    def __init__(
        self,
        username: str,
        password: str,
        session: ClientSession,
    ) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._session = session
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiration: datetime | None = None
        self._user_id: str | None = None

    @property
    def user_id(self) -> str:
        """Return the user ID."""
        if not self._user_id:
            raise FloAuthError("Not authenticated")
        return self._user_id

    @staticmethod
    def _token_payload(auth_response: dict[str, Any]) -> dict[str, Any]:
        """Return the object that actually carries the tokens.

        The Moen gateway wraps them under a ``token`` key
        (``{"token": {"access_token": ...}}``); tolerate a flat shape too so a
        future change on their side doesn't break us outright.
        """
        if isinstance(auth_response, dict):
            token = auth_response.get("token")
            if isinstance(token, dict):
                return token
            return auth_response
        return {}

    @staticmethod
    def _expiry_from(tokens: dict[str, Any]) -> datetime:
        """Return the token expiry, tolerating ``expires_in`` as str or int."""
        try:
            expires_in = int(tokens.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        return datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)

    async def authenticate(self) -> None:
        """Authenticate with the Moen gateway and resolve the Flo user id.

        Exchanges the username/password for a Bearer token at the Moen gateway,
        then looks up the Flo user id (the token no longer carries it) so the
        rest of the client can keep calling the unchanged Flo v2 endpoints.
        """
        _LOGGER.debug("Authenticating with the Moen gateway")

        data = {
            "username": self._username,
            "password": self._password,
            "grant_type": MOEN_GRANT_TYPE,
            "client_id": MOEN_CLIENT_ID,
        }

        try:
            async with self._session.post(
                MOEN_TOKEN_URL,
                json=data,
                timeout=ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                auth_response = await resp.json()

                tokens = self._token_payload(auth_response)
                self._access_token = tokens["access_token"]
                self._refresh_token = tokens.get("refresh_token")
                self._token_expiration = self._expiry_from(tokens)

        except ClientError as err:
            _LOGGER.error("Authentication failed: %s", err)
            raise FloAuthError(f"Authentication failed: {err}") from err
        except KeyError as err:
            _LOGGER.error("Invalid authentication response: %s", err)
            raise FloAuthError(f"Invalid authentication response: {err}") from err

        await self._resolve_user_id()
        _LOGGER.debug("Authentication successful for Flo user %s", self._user_id)

    async def _resolve_user_id(self) -> None:
        """Resolve the Flo user id for the authenticated (migrated) account.

        The Moen token no longer embeds the Flo user id. The app resolves it
        via ``GET /v2/moen/sync/me`` (``FloViewModel.getUserId`` reads the
        ``id`` field) — this returns the *token-scoped* Flo user, which is the
        id the rest of the Flo API (``/locations?userId=`` etc.) authorizes
        against. A lookup by email returns a different record that the API
        rejects with 403, so ``sync/me`` is the source of truth; the email
        lookup is only a last-ditch fallback.

        Uses non-retrying requests so a rejected token surfaces as an auth
        error instead of recursing back into :meth:`authenticate`.
        """
        user_id = None
        try:
            resp = await self._request_with_retry(
                "get", "/moen/sync/me", _retry=False
            )
            if isinstance(resp, dict):
                user_id = resp.get("id")
        except FloRequestError as err:
            _LOGGER.debug("sync/me user-id lookup failed (%s); trying email", err)

        if not user_id:
            try:
                resp = await self._request_with_retry(
                    "get", "/users", _retry=False, params={"email": self._username}
                )
            except FloRequestError as err:
                raise FloAuthError(f"Could not resolve Flo user id: {err}") from err
            if isinstance(resp, list):
                user = resp[0] if resp else None
            else:
                user = resp
            user_id = user.get("id") if isinstance(user, dict) else None

        if not user_id:
            raise FloAuthError("Could not resolve Flo user id for the account")
        self._user_id = user_id

    async def refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            _LOGGER.warning("No refresh token available, re-authenticating")
            await self.authenticate()
            return

        _LOGGER.debug("Refreshing access token")

        data = {
            "grant_type": "refresh_token",
            "client_id": MOEN_CLIENT_ID,
            "refresh_token": self._refresh_token,
        }

        try:
            async with self._session.post(
                MOEN_TOKEN_URL,
                json=data,
                timeout=ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                auth_response = await resp.json()

                tokens = self._token_payload(auth_response)
                self._access_token = tokens["access_token"]
                # Refresh token might be rotated
                if tokens.get("refresh_token"):
                    self._refresh_token = tokens["refresh_token"]

                self._token_expiration = self._expiry_from(tokens)

                _LOGGER.debug("Token refreshed successfully")

        except (ClientError, KeyError) as err:
            _LOGGER.warning("Token refresh failed (%s); re-authenticating", err)
            # If refresh fails (revoked refresh token, malformed response, ...),
            # fall back to a full re-auth. Let any FloAuthError propagate so the
            # coordinator can surface it as ConfigEntryAuthFailed.
            await self.authenticate()

    async def _ensure_token_valid(self) -> None:
        """Ensure we have a valid access token."""
        if not self._access_token or not self._token_expiration:
            await self.authenticate()
            return

        # Refresh if token expires in less than 5 minutes
        if datetime.now(tz=timezone.utc) >= self._token_expiration - timedelta(minutes=5):
            await self.refresh_access_token()

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an authenticated API request.

        On 401 we transparently refresh the token (or fully re-authenticate if
        the refresh token is also bad) and retry the request once. Persistent
        401s are raised as :class:`FloAuthError` so the coordinator can surface
        a reauth flow to the user.
        """
        return await self._request_with_retry(method, path, _retry=True, **kwargs)

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        _retry: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        await self._ensure_token_valid()

        url = f"{API_V2_BASE}{path}" if path.startswith("/") else path

        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"
        headers.setdefault("User-Agent", USER_AGENT)

        if "timeout" not in kwargs:
            kwargs["timeout"] = ClientTimeout(total=20)

        try:
            _LOGGER.debug("Making %s request to %s", method.upper(), url)
            async with self._session.request(
                method, url, headers=headers, **kwargs
            ) as resp:
                if resp.status == 401 and _retry:
                    body = await resp.text()
                    _LOGGER.info(
                        "%s %s returned 401; refreshing credentials and retrying",
                        method.upper(),
                        url,
                    )
                    _LOGGER.debug("401 body: %s", body)
                    self._access_token = None
                    await self._ensure_token_valid()
                    return await self._request_with_retry(
                        method, path, _retry=False, **kwargs
                    )
                if resp.status == 401:
                    body = await resp.text()
                    raise FloAuthError(
                        f"Authentication rejected: {resp.status} {body}"
                    )
                if not resp.ok:
                    body = await resp.text()
                    _LOGGER.error(
                        "%s %s returned %s: %s",
                        method.upper(),
                        url,
                        resp.status,
                        body,
                    )
                    raise FloRequestError(
                        f"Request failed: {resp.status} {body}"
                    )
                # Mode-change endpoints (e.g. POST /locations/{id}/systemMode)
                # return 204 with an empty body — resp.json() would raise
                # "unexpected mimetype" even though the call succeeded.
                if resp.status == 204 or resp.content_length == 0:
                    return {}
                return await resp.json()

        except ClientError as err:
            _LOGGER.error("Request to %s failed: %s", url, err)
            raise FloRequestError(f"Request failed: {err}") from err

    async def get_locations(self) -> list[dict[str, Any]]:
        """Return the account's locations, each with its devices expanded.

        Uses ``GET /v2/locations?userId=...&expand=devices`` (the Moen app's
        ``getLocationByUserId``). The old ``/v2/users/{id}?expand=locations``
        path returns 403 for the Cognito-gateway token, so we discover through
        the locations endpoint instead. The response is ``{"items": [...]}``.
        """
        resp = await self.request(
            "get",
            "/locations",
            params={"userId": self.user_id, "expand": "devices"},
        )
        if isinstance(resp, dict):
            return resp.get("items", []) or []
        if isinstance(resp, list):
            return resp
        return []

    async def get_device_info(self, device_id: str) -> dict[str, Any]:
        """Get device information."""
        return await self.request("get", f"/devices/{device_id}")

    async def get_location_info(self, location_id: str) -> dict[str, Any]:
        """Get location information."""
        return await self.request("get", f"/locations/{location_id}")

    async def get_consumption_info(
        self, location_id: str, start_date: datetime, end_date: datetime
    ) -> dict[str, Any]:
        """Get water consumption information."""
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "interval": "1h",
            "locationId": location_id,
        }
        return await self.request(
            "get", "/water/consumption", params=params
        )

    async def send_presence_ping(self) -> dict[str, Any]:
        """Send presence ping to Flo."""
        return await self.request("post", "/presence/me")

    async def set_valve_state(self, device_id: str, target: str) -> dict[str, Any]:
        """Set valve state (open/closed)."""
        return await self.request(
            "post", f"/devices/{device_id}", json={"valve": {"target": target}}
        )

    async def run_health_test(self, device_id: str) -> dict[str, Any]:
        """Run device health test."""
        return await self.request("post", f"/devices/{device_id}/healthTest/run")

    async def set_location_mode(
        self, location_id: str, mode: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Set location system mode (home/away/sleep)."""
        data: dict[str, Any] = {"target": mode}
        if kwargs:
            data.update(kwargs)

        return await self.request(
            "post", f"/locations/{location_id}/systemMode", json=data
        )


async def async_get_api(
    hass: HomeAssistant, username: str, password: str
) -> FloAPI:
    """Get an authenticated Flo API client."""
    session = async_get_clientsession(hass)
    api = FloAPI(username, password, session)
    await api.authenticate()
    return api
