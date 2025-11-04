"""Flo API client with OAuth2 support."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Moen Flo OAuth2 credentials (extracted from mobile app)
CLIENT_ID = "3baec26f-0e8b-4e1d-84b0-e178f05ea0a5"
CLIENT_SECRET = "3baec26f-0e8b-4e1d-84b0-e178f05ea0a5"

# API endpoints
API_BASE = "https://api-gw.meetflo.com/api"
API_V1_BASE = f"{API_BASE}/v1"
API_V2_BASE = f"{API_BASE}/v2"


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

    async def authenticate(self) -> None:
        """Authenticate with the Flo API using OAuth2 password grant."""
        _LOGGER.debug("Authenticating with Flo API using OAuth2")

        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "password",
            "username": self._username,
            "password": self._password,
        }

        try:
            async with self._session.post(
                f"{API_V1_BASE}/oauth2/token",
                json=data,
                timeout=ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                auth_response = await resp.json()

                self._access_token = auth_response["access_token"]
                self._refresh_token = auth_response["refresh_token"]
                self._user_id = auth_response["user_id"]

                # Calculate expiration (expires_in is in seconds)
                expires_in = auth_response["expires_in"]
                self._token_expiration = datetime.now() + timedelta(seconds=expires_in)

                _LOGGER.debug(
                    "Authentication successful, token expires in %d seconds", expires_in
                )

        except ClientError as err:
            _LOGGER.error("Authentication failed: %s", err)
            raise FloAuthError(f"Authentication failed: {err}") from err
        except KeyError as err:
            _LOGGER.error("Invalid authentication response: %s", err)
            raise FloAuthError(f"Invalid authentication response: {err}") from err

    async def refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            _LOGGER.warning("No refresh token available, re-authenticating")
            await self.authenticate()
            return

        _LOGGER.debug("Refreshing access token")

        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        try:
            async with self._session.post(
                f"{API_V1_BASE}/oauth2/token",
                json=data,
                timeout=ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                auth_response = await resp.json()

                self._access_token = auth_response["access_token"]
                # Refresh token might be rotated
                if "refresh_token" in auth_response:
                    self._refresh_token = auth_response["refresh_token"]

                expires_in = auth_response["expires_in"]
                self._token_expiration = datetime.now() + timedelta(seconds=expires_in)

                _LOGGER.debug("Token refreshed successfully")

        except ClientError as err:
            _LOGGER.error("Token refresh failed: %s, re-authenticating", err)
            # If refresh fails, try full authentication
            await self.authenticate()

    async def _ensure_token_valid(self) -> None:
        """Ensure we have a valid access token."""
        if not self._access_token or not self._token_expiration:
            await self.authenticate()
            return

        # Refresh if token expires in less than 5 minutes
        if datetime.now() >= self._token_expiration - timedelta(minutes=5):
            await self.refresh_access_token()

    async def request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an authenticated API request."""
        await self._ensure_token_valid()

        # Build full URL
        url = f"{API_V2_BASE}{path}" if path.startswith("/") else path

        # Set authorization header with Bearer token
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._access_token}"

        # Set default timeout if not specified
        if "timeout" not in kwargs:
            kwargs["timeout"] = ClientTimeout(total=20)

        try:
            _LOGGER.debug("Making %s request to %s", method.upper(), url)
            async with self._session.request(
                method, url, headers=headers, **kwargs
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

        except ClientError as err:
            _LOGGER.error("Request to %s failed: %s", url, err)
            raise FloRequestError(f"Request failed: {err}") from err

    async def get_user_info(
        self, include_locations: bool = True, include_alarm_settings: bool = False
    ) -> dict[str, Any]:
        """Get user information."""
        params = {}
        expand_list = []

        if include_locations:
            expand_list.append("locations")
        if include_alarm_settings:
            expand_list.append("alarmSettings")

        if expand_list:
            params["expand"] = ",".join(expand_list)

        return await self.request("get", f"/users/{self.user_id}", params=params)

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
            "post", f"/locations/{location_id}/systemMode", json={"systemMode": data}
        )


async def async_get_api(
    hass: HomeAssistant, username: str, password: str
) -> FloAPI:
    """Get an authenticated Flo API client."""
    session = async_get_clientsession(hass)
    api = FloAPI(username, password, session)
    await api.authenticate()
    return api
