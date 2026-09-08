import time
import logging
from pathlib import Path

import jwt
import httpx

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_JWT_WINDOW_SECONDS = 540   # 9 minutes — safely under GitHub's 10-minute maximum
_IAT_BACKDATE_SECONDS = 60  # Back-date iat to tolerate minor clock skew
_TOKEN_BUFFER_SECONDS = 60  # Refresh installation token 60s before expiry


class GitHubAuthService:
    """
    Mints GitHub App JWTs and exchanges them for per-installation access tokens.
    Tokens are cached in-memory and refreshed proactively before expiry.
    """

    def __init__(
        self,
        app_id: int,
        private_key_path: str,
        private_key_content: str = "",
    ) -> None:
        self._app_id = app_id
        # Inline content takes precedence over the file path — used in cloud deployments
        # (Databricks, etc.) where storing the PEM as a secret string is more practical.
        if private_key_content:
            self._private_key = private_key_content
        else:
            self._private_key = Path(private_key_path).read_text(encoding="utf-8")
        # {installation_id: (token, expires_at_epoch)}
        self._token_cache: dict[int, tuple[str, float]] = {}

    def _generate_jwt(self) -> str:
        now = int(time.time())
        iat = now - _IAT_BACKDATE_SECONDS
        # exp is anchored to iat so the window never exceeds GitHub's 10-minute hard limit.
        # Using now + 600 with iat = now - 60 would produce an 11-minute window → 401.
        exp = iat + _JWT_WINDOW_SECONDS
        payload = {"iat": iat, "exp": exp, "iss": str(self._app_id)}
        logger.debug(
            "Minting JWT: app_id=%d  iat=%d  exp=%d  window=%ds",
            self._app_id, iat, exp, exp - iat,
        )
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    async def validate_credentials(self) -> None:
        """
        Calls GET /app with the current JWT to verify the App ID and private key
        are consistent. Raises a descriptive ValueError on 401 so the problem
        is caught at startup rather than on the first webhook delivery.
        """
        jwt_token = self._generate_jwt()
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{_GITHUB_API}/app",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        if response.status_code == 401:
            raise ValueError(
                f"GitHub App authentication failed for App ID {self._app_id}. "
                "Verify that GITHUB_APP_ID in .env matches your GitHub App's numeric ID "
                "and that GITHUB_PRIVATE_KEY_PATH points to the private key downloaded "
                "from that exact app (Settings → Private keys)."
            )
        response.raise_for_status()
        app_name = response.json().get("name", "unknown")
        logger.info("GitHub App credentials verified: '%s' (app_id=%d)", app_name, self._app_id)

    async def get_installation_token(self, installation_id: int) -> str:
        cached = self._token_cache.get(installation_id)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at - _TOKEN_BUFFER_SECONDS:
                return token

        jwt_token = self._generate_jwt()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )

        if response.status_code == 401:
            raise ValueError(
                f"401 getting installation token for installation {installation_id} "
                f"(app_id={self._app_id}). "
                "Check GITHUB_APP_ID and GITHUB_PRIVATE_KEY_PATH in .env."
            )
        response.raise_for_status()
        data = response.json()

        token: str = data["token"]
        self._token_cache[installation_id] = (token, time.time() + 3600)
        logger.debug("Minted new installation token for installation %d", installation_id)
        return token
