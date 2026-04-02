"""
AbapGit ADT Backend handler.

Encapsulates all HTTP interactions with the abapGit ADT Backend
(/sap/bc/adt/abapgit/). Because the backend is an optional add-on,
every public method first calls _availability_guard() which returns a
structured error string when the backend is absent, or None when it is
available.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 2.5,
              3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6,
              5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7,
              8.1, 8.2, 8.3, 8.4, 8.5,
              9.1, 9.2, 9.3, 9.4, 9.5,
              11.1, 11.2, 11.3, 11.4, 11.5
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import defusedxml.ElementTree as ET

if TYPE_CHECKING:
    from sap.sap_client import SAPADTClient

_NS = "http://www.sap.com/adt/abapgit"
_NS_PREFIX = f"{{{_NS}}}"

logger = logging.getLogger(__name__)


def _tag(local: str) -> str:
    """Return the Clark-notation tag for the abapgit namespace."""
    return f"{_NS_PREFIX}{local}"


class AbapGitHandler:
    """Handler for abapGit ADT Backend operations."""

    BASE_PATH = "/sap/bc/adt/abapgit/repos"

    def __init__(self, sap_client: "SAPADTClient") -> None:
        self.sap_client = sap_client
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    async def check_availability(self) -> bool:
        """
        Probe the abapGit ADT Backend by sending GET BASE_PATH.

        Returns True on HTTP 200/204, False on 403/404.
        Caches the result in self._available.

        Requirement 1.1, 1.4, 1.5
        """
        url = f"{self.sap_client.base_url}{self.BASE_PATH}"
        params = {"sap-client": self.sap_client.connection.client}
        headers = await self.sap_client._get_appropriate_headers()

        status, _text, _resp_headers = await self.sap_client._request_with_retry(
            "GET", url, headers=headers, params=params
        )

        if status in (200, 204):
            self._available = True
        elif status in (403, 404):
            self._available = False
        # For any other status we leave _available as-is (don't cache)
        # so the next call will re-probe.

        return bool(self._available)

    def reset_availability_cache(self) -> None:
        """
        Clear the cached availability result.

        Called by SAPADTClient after successful session re-establishment
        so the next abapGit call re-probes the backend.

        Requirement 1.6
        """
        self._available = None

    async def _availability_guard(self) -> Optional[str]:
        """
        Ensure the abapGit ADT Backend is available before proceeding.

        If the cached result is None, performs a fresh availability check.
        Returns None when the backend is available (caller may proceed).
        Returns a structured error string when the backend is unavailable.

        Requirements 1.2, 1.3, 11.1, 11.2, 11.3, 11.4
        """
        if self._available is None:
            await self.check_availability()

        if not self._available:
            return (
                "abapGit ADT Backend is not available on this system. "
                "For on-premise SAP systems, install the ADT Backend add-on from "
                "https://github.com/abapGit/ADT_Backend . "
                "Note: SAP BTP ABAP Environment and SAP S/4HANA Cloud include the "
                "abapGit ADT Backend natively."
            )

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_csrf(self) -> str:
        """
        Fetch a fresh CSRF token from the abapGit endpoint.

        Sends GET BASE_PATH with the x-csrf-token: fetch header and
        returns the token value from the response headers.
        """
        url = f"{self.sap_client.base_url}{self.BASE_PATH}"
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = "fetch"

        _status, _text, resp_headers = await self.sap_client._request_with_retry(
            "GET", url, headers=headers
        )

        token = resp_headers.get("x-csrf-token") or resp_headers.get("X-CSRF-Token", "")
        return token

    def _build_url(self, *parts: str) -> str:
        """
        Join BASE_PATH with additional path segments.

        Example: _build_url("abc123", "pull")
                 → "/sap/bc/adt/abapgit/repos/abc123/pull"
        """
        segments = [self.BASE_PATH.rstrip("/")]
        for part in parts:
            segments.append(part.strip("/"))
        return "/".join(segments)

    def _client_param(self) -> str:
        """Return the SAP client query string parameter."""
        return f"?sap-client={self.sap_client.connection.client}"

    # ------------------------------------------------------------------
    # Repository listing (Requirement 2.x)
    # ------------------------------------------------------------------

    async def list_repos(self) -> str:
        """
        List all abapGit repositories configured on the SAP system.

        GET BASE_PATH?sap-client=<client>
        Parses the XML response and returns a human-readable summary sorted
        ascending by package name.

        Requirements: 2.1, 2.2, 2.3, 2.4, 2.5
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        url = f"{self.sap_client.base_url}{self.BASE_PATH}{self._client_param()}"
        headers = await self.sap_client._get_appropriate_headers()

        status, text, _resp_headers = await self.sap_client._request_with_retry(
            "GET", url, headers=headers
        )

        if status not in (200, 204):
            return f"Failed to list abapGit repositories (HTTP {status})."

        if not text or not text.strip():
            return "No abapGit repositories are configured on this system."

        try:
            root = ET.fromstring(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse abapGit list response: %s", exc)
            return "Failed to parse abapGit repository list response."

        repos: List[Dict[str, Any]] = []
        for repo_el in root.findall(_tag("repository")):
            key = repo_el.get(_tag("key"), "")
            url_val = (repo_el.findtext(_tag("url")) or "").strip()
            package = (repo_el.findtext(_tag("package")) or "").strip()
            branch = (repo_el.findtext(_tag("branch")) or "").strip()
            status_val = (repo_el.findtext(_tag("status")) or "").strip()
            remote_commit = (repo_el.findtext(_tag("remoteCommit")) or "").strip() or None
            local_commit = (repo_el.findtext(_tag("localCommit")) or "").strip() or None
            has_creds_text = (repo_el.findtext(_tag("hasCredentials")) or "false").strip().lower()
            has_credentials = has_creds_text == "true"

            repos.append({
                "key": key,
                "url": url_val,
                "package": package,
                "branch": branch,
                "status": status_val,
                "remote_commit": remote_commit,
                "local_commit": local_commit,
                "has_credentials": has_credentials,
            })

        if not repos:
            return "No abapGit repositories are configured on this system."

        # Sort ascending by package name (Requirement 2.5)
        repos.sort(key=lambda r: r["package"].upper())

        lines = [f"abapGit Repositories ({len(repos)} found):", ""]
        for r in repos:
            lines.append(f"  Package  : {r['package']}")
            lines.append(f"  Key      : {r['key']}")
            lines.append(f"  URL      : {r['url']}")
            lines.append(f"  Branch   : {r['branch']}")
            lines.append(f"  Status   : {r['status']}")
            if r["remote_commit"]:
                lines.append(f"  Remote   : {r['remote_commit']}")
            if r["local_commit"]:
                lines.append(f"  Local    : {r['local_commit']}")
            lines.append(f"  Creds    : {'yes' if r['has_credentials'] else 'no'}")
            lines.append("")

        return "\n".join(lines).rstrip()

    # ------------------------------------------------------------------
    # Get single repository (Requirement 3.x)
    # ------------------------------------------------------------------

    async def get_repo(self, key: str) -> str:
        """
        Retrieve detailed information about a specific abapGit repository.

        GET BASE_PATH/{key}?sap-client=<client>

        Requirements: 3.1, 3.2, 3.3, 3.4
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        url = f"{self.sap_client.base_url}{self._build_url(key)}{self._client_param()}"
        headers = await self.sap_client._get_appropriate_headers()

        status, text, _resp_headers = await self.sap_client._request_with_retry(
            "GET", url, headers=headers
        )

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        if status not in (200, 204):
            return f"Failed to retrieve repository '{key}' (HTTP {status})."

        if not text or not text.strip():
            return f"Repository '{key}' returned an empty response."

        try:
            root = ET.fromstring(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse abapGit get_repo response: %s", exc)
            return f"Failed to parse repository details for '{key}'."

        # The root element may be <abapgit:repository> directly
        repo_el = root if root.tag == _tag("repository") else root.find(_tag("repository"))
        if repo_el is None:
            repo_el = root

        url_val = (repo_el.findtext(_tag("url")) or "").strip()
        package = (repo_el.findtext(_tag("package")) or "").strip()
        branch = (repo_el.findtext(_tag("branch")) or "").strip()
        status_val = (repo_el.findtext(_tag("status")) or "").strip()
        remote_commit = (repo_el.findtext(_tag("remoteCommit")) or "").strip() or None
        local_commit = (repo_el.findtext(_tag("localCommit")) or "").strip() or None
        has_creds_text = (repo_el.findtext(_tag("hasCredentials")) or "false").strip().lower()
        has_credentials = has_creds_text == "true"

        lines = [
            f"Repository: {key}",
            f"  URL      : {url_val}",
            f"  Package  : {package}",
            f"  Branch   : {branch}",
            f"  Status   : {status_val}",
        ]
        if remote_commit:
            lines.append(f"  Remote   : {remote_commit}")
        if local_commit:
            lines.append(f"  Local    : {local_commit}")
        lines.append(f"  Creds    : {'yes' if has_credentials else 'no'}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Create repository (Requirement 4.x)
    # ------------------------------------------------------------------

    async def create_repo(
        self,
        url: str,
        package: str,
        branch: str,
        transport_request: Optional[str] = None,
    ) -> str:
        """
        Link an ABAP package to a Git repository via abapGit.

        POST BASE_PATH?sap-client=<client> with XML payload.
        Fetches a CSRF token before posting.

        Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        csrf_token = await self._fetch_csrf()

        tr_element = ""
        if transport_request:
            tr_element = f"\n  <abapgit:transportRequest>{transport_request}</abapgit:transportRequest>"

        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<abapgit:repository xmlns:abapgit="http://www.sap.com/adt/abapgit">\n'
            f"  <abapgit:url>{url}</abapgit:url>\n"
            f"  <abapgit:package>{package}</abapgit:package>\n"
            f"  <abapgit:branch>{branch}</abapgit:branch>"
            f"{tr_element}\n"
            "</abapgit:repository>"
        )

        post_url = f"{self.sap_client.base_url}{self.BASE_PATH}{self._client_param()}"
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token
        headers["Content-Type"] = "application/xml"

        status, text, resp_headers = await self.sap_client._request_with_retry(
            "POST", post_url, headers=headers, data=payload
        )

        if status == 201:
            # Try to extract the new repo key from the Location header or response body
            location = resp_headers.get("Location", resp_headers.get("location", ""))
            new_key = location.rstrip("/").split("/")[-1] if location else ""
            if not new_key and text:
                try:
                    root = ET.fromstring(text)
                    repo_el = root if root.tag == _tag("repository") else root.find(_tag("repository"))
                    if repo_el is not None:
                        new_key = repo_el.get(_tag("key"), "")
                except Exception:  # noqa: BLE001
                    pass
            key_info = f" (key: {new_key})" if new_key else ""
            return f"Repository successfully linked: {url} → {package}{key_info}."

        if status == 404:
            return f"Package not found: '{package}' does not exist in the SAP system."

        if status == 409:
            return f"Repository already linked: '{url}' is already associated with a package."

        return f"Failed to create repository link (HTTP {status})."

    # ------------------------------------------------------------------
    # Pull from Git repository (Requirement 5.x)
    # ------------------------------------------------------------------

    async def pull(self, key: str, transport_request: Optional[str] = None) -> str:
        """
        Pull the latest changes from a Git repository into the SAP system.

        POST BASE_PATH/{key}/pull?sap-client=<client> with CSRF token.
        Optionally includes a transport request in the XML payload.

        Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        csrf_token = await self._fetch_csrf()

        tr_element = ""
        if transport_request:
            tr_element = (
                f"\n  <abapgit:transportRequest>{transport_request}"
                f"</abapgit:transportRequest>"
            )

        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<abapgit:pull xmlns:abapgit="http://www.sap.com/adt/abapgit">'
            f"{tr_element}\n"
            "</abapgit:pull>"
        )

        pull_url = (
            f"{self.sap_client.base_url}"
            f"{self._build_url(key, 'pull')}"
            f"{self._client_param()}"
        )
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token
        headers["Content-Type"] = "application/xml"

        status, text, _resp_headers = await self.sap_client._request_with_retry(
            "POST", pull_url, headers=headers, data=payload
        )

        if status in (200, 204):
            return f"Pull completed successfully for repository '{key}'."

        # Conflict: HTTP 409 or body containing "conflict"
        if status == 409 or (text and "conflict" in text.lower()):
            return (
                f"Pull failed for repository '{key}': conflicting objects detected. "
                "Resolve the conflicts and retry."
            )

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        if status == 400:
            text_lower = (text or "").lower()
            if "credentials" in text_lower:
                return (
                    f"Pull failed for repository '{key}': Git credentials are missing or invalid. "
                    "Use abapgit_set_credentials to configure Git credentials for this repository."
                )
            if "transport" in text_lower:
                return (
                    f"Pull failed for repository '{key}': a transport request is required. "
                    "Provide a transport request number and retry."
                )

        return f"Pull failed for repository '{key}' (HTTP {status})."

    # ------------------------------------------------------------------
    # Push to Git repository (Requirement 8.x)
    # ------------------------------------------------------------------

    async def push(self, key: str) -> str:
        """
        Push committed changes from the SAP system to the remote Git repository.

        POST BASE_PATH/{key}/push?sap-client=<client> with CSRF token.

        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        csrf_token = await self._fetch_csrf()

        push_url = (
            f"{self.sap_client.base_url}"
            f"{self._build_url(key, 'push')}"
            f"{self._client_param()}"
        )
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token

        status, text, _resp_headers = await self.sap_client._request_with_retry(
            "POST", push_url, headers=headers
        )

        if status in (200, 204):
            return f"Push completed successfully for repository '{key}'."

        text_lower = (text or "").lower()

        # Non-fast-forward / rejected
        if "non-fast-forward" in text_lower or "rejected" in text_lower:
            return (
                f"Push failed for repository '{key}': the remote has changes that are not in your local copy. "
                "Pull the latest changes first, then retry the push."
            )

        # Authentication failure
        if status == 401 or "authentication" in text_lower or "credentials" in text_lower:
            return (
                f"Push failed for repository '{key}': authentication failed. "
                "Verify your Git credentials using abapgit_set_credentials."
            )

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        return f"Push failed for repository '{key}' (HTTP {status})."

    # ------------------------------------------------------------------
    # Staging (Requirement 6.x)
    # ------------------------------------------------------------------

    async def get_staging(self, key: str) -> str:
        """
        Retrieve the list of staged and unstaged objects for a repository.

        GET BASE_PATH/{key}/staging?sap-client=<client>
        Parses the XML response and returns each object's name, type,
        state (staged/unstaged), and change_type (new/modified/deleted).

        Requirements: 6.1, 6.2
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        url = (
            f"{self.sap_client.base_url}"
            f"{self._build_url(key, 'staging')}"
            f"{self._client_param()}"
        )
        headers = await self.sap_client._get_appropriate_headers()

        status, text, _resp_headers = await self.sap_client._request_with_retry(
            "GET", url, headers=headers
        )

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        if status not in (200, 204):
            return f"Failed to retrieve staging area for repository '{key}' (HTTP {status})."

        if not text or not text.strip():
            return f"Staging area for repository '{key}' is empty."

        try:
            root = ET.fromstring(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse abapGit staging response: %s", exc)
            return f"Failed to parse staging response for repository '{key}'."

        objects_el = root.find(_tag("objects"))
        if objects_el is None:
            objects_el = root

        objects: List[Dict[str, Any]] = []
        for obj_el in objects_el.findall(_tag("object")):
            name = obj_el.get(_tag("name"), "")
            obj_type = obj_el.get(_tag("type"), "")
            state = obj_el.get(_tag("state"), "")
            change_type = obj_el.get(_tag("changeType"), "")
            objects.append({
                "name": name,
                "type": obj_type,
                "state": state,
                "change_type": change_type,
            })

        if not objects:
            return f"No changed objects found in staging area for repository '{key}'."

        staged = [o for o in objects if o["state"] == "staged"]
        unstaged = [o for o in objects if o["state"] != "staged"]

        lines = [
            f"Staging area for repository '{key}' ({len(objects)} objects):",
            f"  Staged: {len(staged)}, Unstaged: {len(unstaged)}",
            "",
        ]
        for obj in objects:
            lines.append(
                f"  [{obj['state']:8s}] {obj['type']:10s} {obj['name']}  ({obj['change_type']})"
            )

        return "\n".join(lines)

    async def stage(self, key: str, objects: List[Dict[str, str]]) -> str:
        """
        Stage selected ABAP objects for commit.

        Validates that objects list is non-empty, then POSTs an XML payload
        to BASE_PATH/{key}/staging with a CSRF token.

        Requirements: 6.3, 6.4, 6.5, 6.6
        """
        if not objects:
            return (
                "Staging failed: at least one object must be selected for staging."
            )

        guard = await self._availability_guard()
        if guard is not None:
            return guard

        csrf_token = await self._fetch_csrf()

        obj_elements = "\n".join(
            f'    <abapgit:object abapgit:name="{o["name"]}" abapgit:type="{o["type"]}"/>'
            for o in objects
        )
        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<abapgit:staging xmlns:abapgit="http://www.sap.com/adt/abapgit">\n'
            "  <abapgit:objects>\n"
            f"{obj_elements}\n"
            "  </abapgit:objects>\n"
            "</abapgit:staging>"
        )

        stage_url = (
            f"{self.sap_client.base_url}"
            f"{self._build_url(key, 'staging')}"
            f"{self._client_param()}"
        )
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token
        headers["Content-Type"] = "application/xml"

        status, _text, _resp_headers = await self.sap_client._request_with_retry(
            "POST", stage_url, headers=headers, data=payload
        )

        if status == 200:
            return f"Successfully staged {len(objects)} object(s) for repository '{key}'."

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        return f"Staging failed for repository '{key}' (HTTP {status})."

    # ------------------------------------------------------------------
    # Commit (Requirement 7.x)
    # ------------------------------------------------------------------

    async def commit(
        self,
        key: str,
        message: str,
        author_name: str,
        author_email: str,
    ) -> str:
        """
        Commit staged ABAP objects to the linked Git repository.

        Validates message (non-empty/non-whitespace) and author_email
        (basic email pattern) before making any HTTP call.
        POSTs an XML payload to BASE_PATH/{key}/commit with a CSRF token.

        Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7
        """
        # Requirement 7.3: reject empty/whitespace commit messages
        if not message or not message.strip():
            return "Commit failed: a commit message is required."

        # Requirement 7.4: reject invalid email addresses
        # Valid: exactly one '@', non-empty local part, non-empty domain part
        at_count = author_email.count("@")
        if at_count != 1:
            return (
                "Commit failed: a valid author email address is required "
                f"(got: {author_email!r})."
            )
        local_part, domain_part = author_email.split("@", 1)
        if not local_part or not domain_part:
            return (
                "Commit failed: a valid author email address is required "
                f"(got: {author_email!r})."
            )

        guard = await self._availability_guard()
        if guard is not None:
            return guard

        csrf_token = await self._fetch_csrf()

        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<abapgit:commit xmlns:abapgit="http://www.sap.com/adt/abapgit">\n'
            f"  <abapgit:message>{message}</abapgit:message>\n"
            "  <abapgit:author>\n"
            f"    <abapgit:name>{author_name}</abapgit:name>\n"
            f"    <abapgit:email>{author_email}</abapgit:email>\n"
            "  </abapgit:author>\n"
            "</abapgit:commit>"
        )

        commit_url = (
            f"{self.sap_client.base_url}"
            f"{self._build_url(key, 'commit')}"
            f"{self._client_param()}"
        )
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token
        headers["Content-Type"] = "application/xml"

        status, text, _resp_headers = await self.sap_client._request_with_retry(
            "POST", commit_url, headers=headers, data=payload
        )

        if status == 200:
            # Try to extract commit hash from response body
            commit_hash: Optional[str] = None
            if text:
                try:
                    root = ET.fromstring(text)
                    commit_hash = (
                        root.findtext(_tag("commitHash"))
                        or root.findtext(_tag("commit"))
                        or root.get(_tag("commitHash"))
                    )
                except Exception:  # noqa: BLE001
                    pass
            hash_info = f" (commit: {commit_hash})" if commit_hash else ""
            return f"Commit successful for repository '{key}'{hash_info}."

        text_lower = (text or "").lower()

        # Requirement 7.6: no staged objects
        if "no staged objects" in text_lower or "nothing to commit" in text_lower:
            return (
                f"Commit failed for repository '{key}': there are no staged objects to commit. "
                "Use abapgit_stage to stage objects first."
            )

        # Requirement 7.7: authentication failure
        if status == 401 or "authentication" in text_lower or "credentials" in text_lower:
            return (
                f"Commit failed for repository '{key}': authentication with the remote Git "
                "repository failed. Verify your Git credentials using abapgit_set_credentials."
            )

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        return f"Commit failed for repository '{key}' (HTTP {status})."

    # ------------------------------------------------------------------
    # Delete repository (Requirement 9.x)
    # ------------------------------------------------------------------

    async def delete_repo(self, key: str) -> str:
        """
        Unlink an ABAP package from its Git repository.

        DELETE BASE_PATH/{key}?sap-client=<client> with CSRF token.
        Does NOT delete any ABAP objects from the SAP system.

        Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
        """
        guard = await self._availability_guard()
        if guard is not None:
            return guard

        csrf_token = await self._fetch_csrf()

        del_url = f"{self.sap_client.base_url}{self._build_url(key)}{self._client_param()}"
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token

        status, _text, _resp_headers = await self.sap_client._request_with_retry(
            "DELETE", del_url, headers=headers
        )

        if status in (200, 204):
            return f"Repository '{key}' successfully unlinked. No ABAP objects were deleted."

        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        return f"Failed to delete repository '{key}' (HTTP {status})."

    # ------------------------------------------------------------------
    # Credentials (Requirement 10.x)
    # ------------------------------------------------------------------

    async def set_credentials(self, key: str, secret_name: str) -> str:
        """
        Store Git credentials for a repository by reading them from AWS Secrets Manager.

        Retrieves the secret JSON from AWS Secrets Manager, extracts the
        username and password/token, then POSTs a credentials XML payload to
        BASE_PATH/{key}/credentials with a CSRF token.

        The password/token value is NEVER included in any returned string or
        log message.

        Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8
        """
        import json

        from utils.secret_reader import SecretReader

        # Requirement 10.1, 10.3: retrieve secret from AWS Secrets Manager
        raw_secret = SecretReader.read_aws_secret(secret_name)
        if raw_secret is None:
            return (
                f"Failed to retrieve secret '{secret_name}' from AWS Secrets Manager. "
                "Verify the secret name and that the IAM role has secretsmanager:GetSecretValue permission."
            )

        # Requirement 10.2: parse JSON and accept 'password' or 'token' key
        try:
            creds = json.loads(raw_secret)
        except (json.JSONDecodeError, ValueError):
            return (
                f"Secret '{secret_name}' is not valid JSON. "
                "The secret must be a JSON object with 'username' and 'password' (or 'token') keys."
            )

        username = creds.get("username")
        password_or_token = creds.get("password") or creds.get("token")

        if not username:
            return (
                f"Secret '{secret_name}' is missing the required 'username' field."
            )
        if not password_or_token:
            return (
                f"Secret '{secret_name}' is missing a 'password' or 'token' field."
            )

        guard = await self._availability_guard()
        if guard is not None:
            return guard

        # Requirement 10.5: fetch CSRF token
        csrf_token = await self._fetch_csrf()

        payload = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<abapgit:credentials xmlns:abapgit="http://www.sap.com/adt/abapgit">\n'
            f"  <abapgit:username>{username}</abapgit:username>\n"
            f"  <abapgit:password>{password_or_token}</abapgit:password>\n"
            "</abapgit:credentials>"
        )

        creds_url = (
            f"{self.sap_client.base_url}"
            f"{self._build_url(key, 'credentials')}"
            f"{self._client_param()}"
        )
        headers = await self.sap_client._get_appropriate_headers()
        headers["x-csrf-token"] = csrf_token
        headers["Content-Type"] = "application/xml"

        status, _text, _resp_headers = await self.sap_client._request_with_retry(
            "POST", creds_url, headers=headers, data=payload
        )

        # Requirement 10.7: success on 200
        if status == 200:
            return f"Git credentials for repository '{key}' stored successfully."

        # Requirement 10.8: 404 → repository not found
        if status == 404:
            return f"Repository not found: no abapGit repository with key '{key}'."

        return f"Failed to set credentials for repository '{key}' (HTTP {status})."
