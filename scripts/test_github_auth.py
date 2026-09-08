"""
Run this script to verify GitHub App credentials before starting the full app.

    python scripts/test_github_auth.py

It prints the JWT claims, calls GET /app, and reports exactly what GitHub returns.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()


def _load_config():
    app_id_raw = os.getenv("GITHUB_APP_ID", "")
    key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH", "./certs/private_key.pem")
    if not app_id_raw:
        sys.exit("ERROR: GITHUB_APP_ID is not set in .env")
    try:
        app_id = int(app_id_raw)
    except ValueError:
        sys.exit(f"ERROR: GITHUB_APP_ID must be an integer, got: {app_id_raw!r}")
    key_file = Path(key_path)
    if not key_file.exists():
        sys.exit(f"ERROR: Private key not found at {key_file.resolve()}")
    return app_id, key_file.read_text(encoding="utf-8"), key_path


def _mint_jwt(app_id: int, private_key: str) -> tuple[str, dict]:
    now = int(time.time())
    iat = now - 60
    exp = iat + 540   # 9-minute window — under GitHub's 10-minute max
    claims = {"iat": iat, "exp": exp, "iss": str(app_id)}
    token = jwt.encode(claims, private_key, algorithm="RS256")
    return token, claims


async def _test(app_id: int, private_key: str, key_path: str):
    print(f"\n{'='*60}")
    print(f"  GitHub App Auth Diagnostic")
    print(f"{'='*60}")
    print(f"  App ID          : {app_id}")
    print(f"  Private key path: {key_path}")
    print(f"  Key loaded      : {len(private_key)} chars, "
          f"starts with {'RSA PRIVATE KEY' if 'RSA PRIVATE KEY' in private_key else 'PRIVATE KEY'}")
    print(f"  System time     : {int(time.time())} (Unix epoch)")

    token, claims = _mint_jwt(app_id, private_key)
    print(f"\n  JWT claims:")
    print(f"    iss = {claims['iss']}")
    print(f"    iat = {claims['iat']}  (now - 60s)")
    print(f"    exp = {claims['exp']}  (iat + 540s = 9-min window)")

    print(f"\n  Calling GET https://api.github.com/app ...")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            "https://api.github.com/app",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    print(f"  HTTP status     : {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        print(f"\n  ✅ SUCCESS")
        print(f"  App name        : {data.get('name')}")
        print(f"  App slug        : {data.get('slug')}")
        print(f"  Owner           : {data.get('owner', {}).get('login')}")
    elif response.status_code == 401:
        print(f"\n  ❌ 401 UNAUTHORIZED")
        print(f"  GitHub rejected the JWT. Likely causes:")
        print(f"    1. GITHUB_APP_ID ({app_id}) doesn't match the private key's app")
        print(f"    2. The private key was revoked or re-generated — download a fresh one")
        print(f"    3. System clock is significantly wrong (check `date` / time sync)")
        print(f"  Raw response: {response.text[:300]}")
    else:
        print(f"\n  ⚠️  Unexpected status: {response.status_code}")
        print(f"  Response: {response.text[:300]}")

    print(f"{'='*60}\n")


def main():
    app_id, private_key, key_path = _load_config()
    asyncio.run(_test(app_id, private_key, key_path))


if __name__ == "__main__":
    main()
