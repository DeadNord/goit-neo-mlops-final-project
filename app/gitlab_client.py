"""Utility helpers to trigger GitLab pipelines via the trigger token API."""

from __future__ import annotations

import logging
from typing import Dict, Optional
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)


class GitLabTriggerError(RuntimeError):
    """Raised when the GitLab trigger API returns an error response."""


def trigger_gitlab_pipeline(
    *,
    base_url: str,
    project: str,
    token: str,
    ref: str,
    variables: Optional[Dict[str, str]] = None,
    timeout: int = 10,
) -> Dict:
    """Trigger a GitLab CI pipeline using the trigger token API.

    Args:
        base_url: GitLab instance base URL (e.g. ``https://gitlab.com``).
        project: Numeric ID or ``namespace/project`` path of the project.
        token: Trigger token created in the GitLab project's CI/CD settings.
        ref: Branch or tag name for the pipeline to run on.
        variables: Optional mapping of CI variables to include in the trigger.
        timeout: HTTP request timeout in seconds.

    Returns:
        Parsed JSON response from the GitLab API.

    Raises:
        GitLabTriggerError: If GitLab returns a non-2xx response or JSON cannot
            be decoded.
        requests.RequestException: For transport-level issues.
    """

    # Construct API endpoint. ``quote_plus`` handles namespace paths with slashes.
    project_encoded = quote_plus(project)
    url = f"{base_url.rstrip('/')}/api/v4/projects/{project_encoded}/trigger/pipeline"

    payload = {"token": token, "ref": ref}
    if variables:
        for key, value in variables.items():
            payload[f"variables[{key}]"] = value

    logger.debug(
        "Triggering GitLab pipeline: url=%s ref=%s variables=%s",
        url,
        ref,
        bool(variables),
    )

    response = requests.post(url, data=payload, timeout=timeout)
    if not response.ok:
        raise GitLabTriggerError(
            f"GitLab trigger failed with status {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise GitLabTriggerError("GitLab trigger response was not valid JSON") from exc

    logger.info(
        "GitLab pipeline triggered successfully: project=%s ref=%s pipeline_id=%s",
        project,
        ref,
        data.get("id"),
    )
    return data
