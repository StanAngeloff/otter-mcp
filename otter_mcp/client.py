from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
import pyotp

API_BASE = "https://otter.ai/forward/api/v1/"

_STATE_DIR = Path(
    os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
) / "otter-mcp"
_COOKIE_PATH = _STATE_DIR / "cookies.json"


class OtterError(Exception):
    pass


def _load_cookies() -> list[dict]:
    try:
        return json.loads(_COOKIE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_cookies(jar: httpx.Cookies) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for cookie in jar.jar:
        entries.append({
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
        })
    _COOKIE_PATH.write_text(json.dumps(entries, indent=2))
    _COOKIE_PATH.chmod(0o600)


class OtterClient:
    def __init__(
        self,
        email: str,
        password: str,
        totp_secret: str,
    ) -> None:
        self._email = email
        self._password = password
        self._totp_secret = totp_secret
        self._userid: str | None = None
        self._speakers: dict[int, str] | None = None
        self._device_uuid = str(uuid.uuid4())
        self._http = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=30.0,
            headers={"referer": "https://otter.ai/"},
        )
        for c in _load_cookies():
            self._http.cookies.set(
                c["name"], c["value"], domain=c.get("domain"), path=c.get("path")
            )

    @property
    def _csrf(self) -> str | None:
        for cookie in self._http.cookies.jar:
            if cookie.name == "csrftoken":
                return cookie.value
        return None

    def _csrf_headers(self) -> dict[str, str]:
        csrf = self._csrf
        return {"x-csrftoken": csrf} if csrf else {}

    async def login(self) -> None:
        await self._http.get("login_csrf")

        resp = await self._http.post(
            "login",
            params={
                "username": self._email,
                "device_uuid": self._device_uuid,
            },
            auth=(self._email, self._password),
            headers=self._csrf_headers(),
        )
        if resp.status_code != 200:
            raise OtterError(f"Login failed with status {resp.status_code}")

        await self._http.get("login_csrf")

        code = pyotp.TOTP(self._totp_secret).now()
        resp = await self._http.post(
            "verify_otp_token",
            data={
                "token": code,
                "two_factor_type": "totp",
                "device_uuid": self._device_uuid,
                "verify_is_allowed": "1",
            },
            headers=self._csrf_headers(),
        )
        if resp.status_code != 200:
            raise OtterError(f"OTP verification failed with status {resp.status_code}")

        profile = await self._http.get(
            "user/profile", headers=self._csrf_headers()
        )
        if profile.status_code != 200:
            raise OtterError(f"Profile fetch failed with status {profile.status_code}")
        user = profile.json().get("user", {})
        self._userid = str(user["id"])

        _save_cookies(self._http.cookies)

    async def try_resume(self) -> bool:
        if not self._csrf:
            return False
        resp = await self._http.get(
            "login_csrf", headers=self._csrf_headers()
        )
        if resp.status_code != 200:
            return False
        data = resp.json()
        if not data.get("logged-in"):
            return False
        profile = await self._http.get(
            "user/profile", headers=self._csrf_headers()
        )
        if profile.status_code != 200:
            return False
        user = profile.json().get("user", {})
        self._userid = str(user["id"])
        return True

    async def close(self) -> None:
        _save_cookies(self._http.cookies)
        await self._http.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        headers.update(self._csrf_headers())
        kwargs["headers"] = headers

        resp = await self._http.request(method, endpoint, **kwargs)

        if resp.status_code == 401:
            await self.login()
            headers.update(self._csrf_headers())
            kwargs["headers"] = headers
            resp = await self._http.request(method, endpoint, **kwargs)

        if resp.status_code != 200:
            raise OtterError(f"{method} {endpoint}: HTTP {resp.status_code}")

        return resp.json()

    # ── Implemented endpoints ──────────────────────────────────────────

    async def list_conversations(
        self, page_size: int = 20, last_load_ts: int | None = None
    ) -> dict:
        params: dict = {
            "page_size": page_size,
            "source": "home",
            "funnel": "home_feed",
            "speech_metadata": "true",
            "use_serializer": "HomeFeedSpeechWithoutSharedGroupsSerializer",
        }
        if last_load_ts is not None:
            params["last_load_ts"] = last_load_ts
        return await self._request("GET", "available_speeches", params=params)

    async def get_speech(self, otid: str) -> dict:
        data = await self._request("GET", "speech", params={"otid": otid})
        return data.get("speech", data)

    async def get_speakers(self) -> dict[int, str]:
        if self._speakers is not None:
            return self._speakers
        data = await self._request(
            "GET", "speakers", params={"user_id": self._userid}
        )
        self._speakers = {
            s["id"]: s["speaker_name"] for s in data.get("speakers", [])
        }
        return self._speakers

    async def search(
        self, query: str, size: int = 500, otid: str | None = None
    ) -> dict:
        raise NotImplementedError(
            "Search not yet implemented — awaiting HAR capture"
        )

    # ── Stubbed endpoints (not exposed as MCP tools yet) ───────────────

    async def get_summary(self, otid: str) -> dict:
        # TODO: expose as MCP tool
        return await self._request(
            "GET", "abstract_summary", params={"otid": otid}
        )

    async def get_action_items(self, otid: str) -> dict:
        # TODO: expose as MCP tool
        return await self._request(
            "GET", "speech_action_items", params={"otid": otid}
        )

    async def get_folders(self) -> dict:
        # TODO: expose as MCP tool
        return await self._request("GET", "folders")

    async def bulk_export(
        self, otids: list[str], formats: list[str] | None = None
    ) -> dict:
        # TODO: expose as MCP tool
        return await self._request(
            "POST",
            "bulk_export",
            params={"userid": self._userid},
            data={
                "formats": formats or ["txt"],
                "speech_otid_list": otids,
            },
        )
