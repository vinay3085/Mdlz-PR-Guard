import logging
import httpx

from app.services.interfaces import IGitHubService
from app.services.github_auth import GitHubAuthService

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_DEFAULT_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubService(IGitHubService):
    """Concrete implementation of IGitHubService using the GitHub REST API."""

    def __init__(self, auth_service: GitHubAuthService) -> None:
        self._auth = auth_service

    async def _auth_headers(self, installation_id: int) -> dict:
        token = await self._auth.get_installation_token(installation_id)
        return {**_DEFAULT_HEADERS, "Authorization": f"Bearer {token}"}

    async def get_pr_diff(
        self, installation_id: int, repo_full_name: str, pr_number: int
    ) -> str:
        headers = await self._auth_headers(installation_id)
        headers["Accept"] = "application/vnd.github.diff"

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(
                f"{_GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}",
                headers=headers,
            )
            response.raise_for_status()
            return response.text

    async def post_review(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        body: str,
        event: str,
    ) -> None:
        headers = await self._auth_headers(installation_id)
        payload = {"commit_id": commit_sha, "body": body, "event": event}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{_GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/reviews",
                headers=headers,
                json=payload,
            )
            if response.status_code not in (200, 201):
                logger.error(
                    "Failed to post review on %s#%d: %d %s",
                    repo_full_name,
                    pr_number,
                    response.status_code,
                    response.text[:200],
                )
                response.raise_for_status()

    async def create_check_run(
        self,
        installation_id: int,
        repo_full_name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> None:
        headers = await self._auth_headers(installation_id)
        payload = {
            "name": "Mdlz PR Guard",
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{_GITHUB_API}/repos/{repo_full_name}/check-runs",
                headers=headers,
                json=payload,
            )
            if response.status_code not in (200, 201):
                logger.error(
                    "Failed to create check-run on %s@%s: %d %s",
                    repo_full_name,
                    head_sha[:8],
                    response.status_code,
                    response.text[:200],
                )
                response.raise_for_status()
