import os
import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class DatabricksService:
    """Simple Databricks Workspace fetcher.

    Exports files under a workspace path into a target directory using the
    Databricks Workspace API. Requires `DATABRICKS_HOST` and `DATABRICKS_TOKEN`.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.host = settings.databricks_host
        self.token = settings.databricks_token
        if self.host and self.host.startswith("https://"):
            self.base = self.host.rstrip("/")
        elif self.host:
            self.base = f"https://{self.host.rstrip('/') }"
        else:
            self.base = ""

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def export_path_to_dir(self, workspace_path: str, target_dir: str) -> None:
        """Recursively export the workspace contents at `workspace_path` into `target_dir`.

        This uses the Workspace API (`/api/2.0/workspace/list` + `/api/2.0/workspace/export`).
        """
        if not self.base or not self.token:
            raise RuntimeError("Databricks host or token not configured")

        client = httpx.Client(base_url=self.base, headers=self._headers(), timeout=30.0)

        def _recurse(path: str, out_dir: str) -> None:
            # Ensure output dir exists
            os.makedirs(out_dir, exist_ok=True)

            try:
                r = client.post("/api/2.0/workspace/list", json={"path": path})
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.warning("Databricks list failed for %s: %s", path, e)
                return

            for item in data.get("objects", []) or []:
                obj_type = item.get("object_type")
                obj_path = item.get("path")
                name = os.path.basename(obj_path.rstrip("/"))
                if obj_type == "DIRECTORY":
                    _recurse(obj_path, os.path.join(out_dir, name))
                else:
                    # Export file/notebook
                    try:
                        exp = client.get(
                            "/api/2.0/workspace/export",
                            params={"path": obj_path, "format": "SOURCE"},
                        )
                        exp.raise_for_status()
                        content = exp.json().get("content")
                        if content is None:
                            # Some objects (binary) may not export as SOURCE; skip
                            logger.debug("Databricks object %s returned no content", obj_path)
                            continue
                        # content is base64 or raw depending on API; try to write raw
                        out_path = os.path.join(out_dir, name)
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception as e:
                        logger.warning("Failed to export %s: %s", obj_path, e)

        _recurse(workspace_path, target_dir)
