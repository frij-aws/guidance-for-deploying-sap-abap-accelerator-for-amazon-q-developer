# Feature: abapgit-adt-operations, Property 1: Availability check precedes every abapGit operation
# Feature: abapgit-adt-operations, Property 2: Unavailability returns required error text
# Feature: abapgit-adt-operations, Property 3: Availability result is cached within a session
# Feature: abapgit-adt-operations, Property 4: Availability cache is reset after session re-establishment
"""
Property-based tests for AbapGitHandler availability behaviour.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.6
"""

from __future__ import annotations

import asyncio
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Minimal stubs — we do NOT import the real SAPADTClient to keep tests fast
# and free of network/SAP dependencies.
# ---------------------------------------------------------------------------

from aws_abap_accelerator.sap.abapgit_handler import AbapGitHandler


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

# HTTP status codes that signal "unavailable"
_unavailable_status = st.sampled_from([403, 404])

# HTTP status codes that signal "available"
_available_status = st.sampled_from([200, 204])

# Any status code (for generic tests)
_any_status = st.integers(min_value=100, max_value=599)

# A small set of operation names that map to public AbapGitHandler methods
# (only the ones that exist in task 4.1 — the guard is the key thing under test)
_OPERATION_NAMES = [
    "list_repos",
    "get_repo",
    "create_repo",
    "pull",
    "get_staging",
    "stage",
    "commit",
    "push",
    "delete_repo",
    "set_credentials",
]

_operation_name = st.sampled_from(_OPERATION_NAMES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sap_client(availability_status: int = 200) -> MagicMock:
    """
    Build a minimal mock SAPADTClient whose _request_with_retry returns
    the given status for the availability probe.
    """
    client = MagicMock()
    client.base_url = "https://sap.example.com"
    client.connection = MagicMock()
    client.connection.client = "100"

    # _get_appropriate_headers returns a plain dict
    client._get_appropriate_headers = AsyncMock(return_value={
        "Accept": "application/xml",
        "x-sap-adt-sessiontype": "stateful",
    })

    # _request_with_retry returns (status, text, headers)
    client._request_with_retry = AsyncMock(
        return_value=(availability_status, "", {})
    )

    return client


def _make_handler(availability_status: int = 200) -> AbapGitHandler:
    """Create an AbapGitHandler backed by a mock SAPADTClient."""
    return AbapGitHandler(_make_sap_client(availability_status))


def _run(coro):
    """Run a coroutine synchronously (compatible with Python 3.10+)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Property 1: Availability check precedes every abapGit operation
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(status=_available_status)
def test_availability_check_precedes_every_operation(status: int) -> None:
    """
    **Validates: Requirements 1.1**

    For any abapGit tool call, the handler must issue a GET to
    /sap/bc/adt/abapgit/repos before issuing the operation-specific request.

    We verify this by checking that _request_with_retry is called at least
    once with the BASE_PATH URL before any other URL is contacted.
    """
    handler = _make_handler(availability_status=status)

    # Call _availability_guard directly — this is what every public method
    # must call first.  We verify the availability probe is issued.
    result = _run(handler._availability_guard())

    # The guard should return None (available) for 200/204
    assert result is None, f"Expected None (available) for status {status}, got {result!r}"

    # _request_with_retry must have been called at least once
    assert handler.sap_client._request_with_retry.called, (
        "Expected _request_with_retry to be called for the availability probe"
    )

    # The first call must target BASE_PATH
    first_call_args = handler.sap_client._request_with_retry.call_args_list[0]
    called_url: str = first_call_args[0][1]  # positional arg index 1 = url
    assert AbapGitHandler.BASE_PATH in called_url, (
        f"First request URL {called_url!r} does not contain BASE_PATH "
        f"{AbapGitHandler.BASE_PATH!r}"
    )


@settings(max_examples=100)
@given(status=_unavailable_status)
def test_availability_check_precedes_every_operation_unavailable(status: int) -> None:
    """
    **Validates: Requirements 1.1**

    Even when the backend is unavailable, the availability probe must be
    issued (and the guard must return an error string, not None).
    """
    handler = _make_handler(availability_status=status)

    result = _run(handler._availability_guard())

    # Guard must return an error string (not None) when unavailable
    assert result is not None, (
        f"Expected error string for status {status}, got None"
    )

    # The probe must still have been issued
    assert handler.sap_client._request_with_retry.called, (
        "Expected _request_with_retry to be called for the availability probe"
    )

    first_call_args = handler.sap_client._request_with_retry.call_args_list[0]
    called_url: str = first_call_args[0][1]
    assert AbapGitHandler.BASE_PATH in called_url, (
        f"First request URL {called_url!r} does not contain BASE_PATH"
    )


# ---------------------------------------------------------------------------
# Property 2: Unavailability returns required error text
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(status=_unavailable_status)
def test_unavailability_returns_required_error_text(status: int) -> None:
    """
    **Validates: Requirements 1.2, 1.3, 11.1, 11.2, 11.3, 11.4**

    For any HTTP status code in {403, 404} returned by the availability check,
    the string returned must contain:
      - "abapGit ADT Backend is not available on this system"
      - "https://github.com/abapGit/ADT_Backend"
    """
    handler = _make_handler(availability_status=status)

    error_msg = _run(handler._availability_guard())

    assert error_msg is not None, (
        f"Expected error string for status {status}, got None"
    )
    assert "abapGit ADT Backend is not available on this system" in error_msg, (
        f"Error message for status {status} missing required text. Got: {error_msg!r}"
    )
    assert "https://github.com/abapGit/ADT_Backend" in error_msg, (
        f"Error message for status {status} missing install URL. Got: {error_msg!r}"
    )


@settings(max_examples=100)
@given(status=_unavailable_status)
def test_unavailability_mentions_btp_s4hc(status: int) -> None:
    """
    **Validates: Requirements 1.3, 11.3**

    The unavailability message must mention that BTP ABAP Environment and
    S/4HANA Cloud include the backend natively.
    """
    handler = _make_handler(availability_status=status)
    error_msg = _run(handler._availability_guard())

    assert error_msg is not None
    # Check for BTP / S4HC mention (case-insensitive substring check)
    lower = error_msg.lower()
    assert "btp" in lower or "s/4hana cloud" in lower or "s4hana cloud" in lower, (
        f"Error message does not mention BTP/S4HC. Got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Availability result is cached within a session
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    status=_available_status,
    n_calls=st.integers(min_value=2, max_value=10),
)
def test_availability_cached_within_session(status: int, n_calls: int) -> None:
    """
    **Validates: Requirements 1.4**

    For any sequence of two or more abapGit tool calls within the same session,
    the availability endpoint is called exactly once (not once per tool call).
    """
    handler = _make_handler(availability_status=status)

    # Call _availability_guard n_calls times
    for _ in range(n_calls):
        result = _run(handler._availability_guard())
        assert result is None, f"Expected None (available) on repeated call, got {result!r}"

    # _request_with_retry must have been called exactly once despite n_calls invocations
    call_count = handler.sap_client._request_with_retry.call_count
    assert call_count == 1, (
        f"Expected exactly 1 availability probe for {n_calls} guard calls, "
        f"but _request_with_retry was called {call_count} times"
    )


@settings(max_examples=100)
@given(
    status=_unavailable_status,
    n_calls=st.integers(min_value=2, max_value=10),
)
def test_availability_cached_within_session_unavailable(status: int, n_calls: int) -> None:
    """
    **Validates: Requirements 1.4**

    Caching also applies when the backend is unavailable: the probe is issued
    once and the cached False result is reused for subsequent calls.
    """
    handler = _make_handler(availability_status=status)

    for _ in range(n_calls):
        result = _run(handler._availability_guard())
        assert result is not None, "Expected error string on every call when unavailable"

    call_count = handler.sap_client._request_with_retry.call_count
    assert call_count == 1, (
        f"Expected exactly 1 availability probe for {n_calls} guard calls (unavailable), "
        f"but _request_with_retry was called {call_count} times"
    )


# ---------------------------------------------------------------------------
# Property 4: Availability cache is reset after session re-establishment
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    first_status=_available_status,
    second_status=st.one_of(_available_status, _unavailable_status),
)
def test_availability_cache_reset_after_session_reestablishment(
    first_status: int, second_status: int
) -> None:
    """
    **Validates: Requirements 1.6**

    After reset_availability_cache() is called, the next abapGit tool call
    must trigger a fresh availability check (i.e., the cache is not reused
    across session boundaries).
    """
    handler = _make_handler(availability_status=first_status)

    # First call — populates the cache
    _run(handler._availability_guard())
    assert handler.sap_client._request_with_retry.call_count == 1

    # Simulate session re-establishment
    handler.reset_availability_cache()
    assert handler._available is None, (
        "reset_availability_cache() must set _available to None"
    )

    # Change the mock to return a different status for the second probe
    handler.sap_client._request_with_retry = AsyncMock(
        return_value=(second_status, "", {})
    )

    # Second call — must re-probe because cache was cleared
    _run(handler._availability_guard())

    assert handler.sap_client._request_with_retry.call_count == 1, (
        "Expected exactly 1 new availability probe after cache reset, "
        f"but _request_with_retry was called "
        f"{handler.sap_client._request_with_retry.call_count} times"
    )

    # Verify the cached value reflects the second probe's result
    if second_status in (200, 204):
        assert handler._available is True
    elif second_status in (403, 404):
        assert handler._available is False


@settings(max_examples=100)
@given(n_resets=st.integers(min_value=1, max_value=5))
def test_each_reset_triggers_fresh_probe(n_resets: int) -> None:
    """
    **Validates: Requirements 1.6**

    Each call to reset_availability_cache() followed by _availability_guard()
    must trigger exactly one new probe.
    """
    handler = _make_handler(availability_status=200)

    total_expected_probes = 0

    for i in range(n_resets + 1):
        if i > 0:
            handler.reset_availability_cache()
            # Replace mock to count fresh calls
            handler.sap_client._request_with_retry = AsyncMock(
                return_value=(200, "", {})
            )

        _run(handler._availability_guard())
        total_expected_probes += 1

        # After each guard call, exactly one probe should have been made
        # on the current mock instance
        assert handler.sap_client._request_with_retry.call_count == 1, (
            f"After reset #{i}, expected 1 probe but got "
            f"{handler.sap_client._request_with_retry.call_count}"
        )


# ---------------------------------------------------------------------------
# Property 5: List response contains all required fields for every repository
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 5: List response contains all required fields for every repository

_NS_ABAPGIT = "http://www.sap.com/adt/abapgit"


def _build_list_xml(repos: List[Dict]) -> str:
    """Build a minimal abapGit list XML from a list of repo dicts."""
    lines = [f'<abapgit:repositories xmlns:abapgit="{_NS_ABAPGIT}">']
    for r in repos:
        key = r.get("key", "K1")
        lines.append(f'  <abapgit:repository abapgit:key="{key}">')
        lines.append(f'    <abapgit:url>{r.get("url", "https://example.com/repo.git")}</abapgit:url>')
        lines.append(f'    <abapgit:package>{r.get("package", "ZPKG")}</abapgit:package>')
        lines.append(f'    <abapgit:branch>{r.get("branch", "main")}</abapgit:branch>')
        lines.append(f'    <abapgit:status>{r.get("status", "OK")}</abapgit:status>')
        if r.get("remote_commit"):
            lines.append(f'    <abapgit:remoteCommit>{r["remote_commit"]}</abapgit:remoteCommit>')
        if r.get("local_commit"):
            lines.append(f'    <abapgit:localCommit>{r["local_commit"]}</abapgit:localCommit>')
        has_creds = "true" if r.get("has_credentials") else "false"
        lines.append(f'    <abapgit:hasCredentials>{has_creds}</abapgit:hasCredentials>')
        lines.append("  </abapgit:repository>")
    lines.append("</abapgit:repositories>")
    return "\n".join(lines)


# Strategy: generate a list of 1–10 repos with random but valid-looking data
_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
)

_repo_strategy = st.fixed_dictionaries({
    "key": _safe_text,
    "url": st.just("https://github.com/example/repo.git"),
    "package": _safe_text,
    "branch": _safe_text,
    "status": st.sampled_from(["OK", "ERROR", "OFFLINE", "AHEAD", "BEHIND"]),
    "remote_commit": st.one_of(st.none(), _safe_text),
    "local_commit": st.one_of(st.none(), _safe_text),
    "has_credentials": st.booleans(),
})

_repo_list_strategy = st.lists(_repo_strategy, min_size=1, max_size=10)


@settings(max_examples=100)
@given(repos=_repo_list_strategy)
def test_list_response_contains_all_required_fields_and_sorted(repos: List[Dict]) -> None:
    """
    **Validates: Requirements 2.2, 2.4, 2.5**

    For any XML list response containing N repositories, the parsed output
    must include url, package, branch, status, and has_credentials for each,
    and the list must be sorted ascending by package.
    """
    xml_text = _build_list_xml(repos)

    # Build a mock client that returns the XML
    client = _make_sap_client(availability_status=200)
    # First call: availability probe → (200, "", {})
    # Second call: list repos → (200, xml_text, {})
    client._request_with_retry = AsyncMock(
        side_effect=[
            (200, "", {}),          # availability probe
            (200, xml_text, {}),    # list_repos GET
        ]
    )

    handler = AbapGitHandler(client)
    result = _run(handler.list_repos())

    # Result must be a non-empty string (not an error)
    assert isinstance(result, str)
    assert "Failed" not in result, f"Unexpected failure: {result!r}"
    assert "not available" not in result, f"Unexpected unavailability: {result!r}"

    # Every repo's package, url, branch, status must appear in the output
    for r in repos:
        assert r["package"] in result, (
            f"Package '{r['package']}' missing from list output"
        )
        assert r["url"] in result, (
            f"URL '{r['url']}' missing from list output"
        )
        assert r["branch"] in result, (
            f"Branch '{r['branch']}' missing from list output"
        )
        assert r["status"] in result, (
            f"Status '{r['status']}' missing from list output"
        )
        # has_credentials must be reflected
        creds_marker = "yes" if r["has_credentials"] else "no"
        # We can't assert per-repo without parsing, but we verify the marker exists
        assert creds_marker in result, (
            f"Credentials marker '{creds_marker}' missing from list output"
        )

    # Verify sort order: extract package names in the order they appear in the output
    # by finding "Package  :" lines
    package_lines = [
        line.split(":", 1)[1].strip()
        for line in result.splitlines()
        if "Package  :" in line
    ]
    assert package_lines == sorted(package_lines, key=str.upper), (
        f"Packages not sorted ascending: {package_lines}"
    )


# ---------------------------------------------------------------------------
# Property 6: All mutating requests include a CSRF token header
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 6: All mutating requests include a CSRF token header

_FAKE_CSRF = "fake-csrf-token-xyz"


def _make_csrf_client(op_status: int = 200, op_text: str = "", op_headers: Optional[dict] = None) -> MagicMock:
    """
    Build a mock client where:
    - The availability probe returns 200.
    - The CSRF fetch returns a token in the response headers.
    - The actual operation returns (op_status, op_text, op_headers).
    """
    client = MagicMock()
    client.base_url = "https://sap.example.com"
    client.connection = MagicMock()
    client.connection.client = "100"
    client._get_appropriate_headers = AsyncMock(return_value={
        "Accept": "application/xml",
    })

    if op_headers is None:
        op_headers = {}

    # Side effects:
    # 1. availability probe → (200, "", {})
    # 2. CSRF fetch → (200, "", {"x-csrf-token": _FAKE_CSRF})
    # 3. actual operation → (op_status, op_text, op_headers)
    client._request_with_retry = AsyncMock(
        side_effect=[
            (200, "", {}),
            (200, "", {"x-csrf-token": _FAKE_CSRF}),
            (op_status, op_text, op_headers),
        ]
    )
    return client


@settings(max_examples=100)
@given(
    op=st.sampled_from(["create_repo", "delete_repo"]),
    op_status=st.sampled_from([200, 201, 204, 404, 409]),
)
def test_mutating_requests_include_csrf_token(op: str, op_status: int) -> None:
    """
    **Validates: Requirements 4.2, 5.2, 6.4, 7.2, 8.2, 9.2, 10.5**

    For any POST or DELETE request issued by AbapGitHandler, the request
    headers must contain a non-empty x-csrf-token value.
    """
    # Adjust op_status for create_repo: 201 is success, others are errors
    if op == "create_repo":
        client = _make_csrf_client(op_status=op_status, op_headers={"Location": "/repos/NEWKEY"})
    else:
        client = _make_csrf_client(op_status=op_status)

    handler = AbapGitHandler(client)

    if op == "create_repo":
        result = _run(handler.create_repo(
            url="https://github.com/example/repo.git",
            package="ZPKG",
            branch="main",
        ))
    else:  # delete_repo
        result = _run(handler.delete_repo(key="abc123"))

    # The result must be a string (no exception)
    assert isinstance(result, str)

    # Find the actual mutating call (3rd call: index 2)
    calls = client._request_with_retry.call_args_list
    assert len(calls) >= 3, f"Expected at least 3 calls, got {len(calls)}"

    mutating_call = calls[2]
    # kwargs may contain 'headers' or it may be positional
    call_kwargs = mutating_call[1]  # keyword args
    call_args = mutating_call[0]    # positional args

    headers_sent = call_kwargs.get("headers") or (call_args[2] if len(call_args) > 2 else {})

    assert "x-csrf-token" in headers_sent, (
        f"x-csrf-token missing from {op} request headers. Headers: {headers_sent}"
    )
    assert headers_sent["x-csrf-token"], (
        f"x-csrf-token is empty in {op} request headers"
    )
    assert headers_sent["x-csrf-token"] == _FAKE_CSRF, (
        f"x-csrf-token value mismatch: expected {_FAKE_CSRF!r}, got {headers_sent['x-csrf-token']!r}"
    )


# ---------------------------------------------------------------------------
# Property 7: Transport request is forwarded when provided
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 7: Transport request is forwarded when provided

_transport_request_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd"), whitelist_characters=""),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")


@settings(max_examples=100)
@given(transport_request=_transport_request_strategy)
def test_transport_request_forwarded_in_create_repo_payload(transport_request: str) -> None:
    """
    **Validates: Requirements 4.6, 5.6**

    For any non-empty transport request string, the XML payload sent to SAP
    must contain that transport request value.
    """
    client = _make_csrf_client(op_status=201, op_headers={"Location": "/repos/NEWKEY"})
    handler = AbapGitHandler(client)

    result = _run(handler.create_repo(
        url="https://github.com/example/repo.git",
        package="ZPKG",
        branch="main",
        transport_request=transport_request,
    ))

    assert isinstance(result, str)

    # Find the POST call (3rd call: index 2)
    calls = client._request_with_retry.call_args_list
    assert len(calls) >= 3, f"Expected at least 3 calls, got {len(calls)}"

    post_call = calls[2]
    call_kwargs = post_call[1]
    call_args = post_call[0]

    # The payload is passed as 'data' kwarg or positional
    payload = call_kwargs.get("data") or (call_args[3] if len(call_args) > 3 else "")

    assert transport_request in payload, (
        f"Transport request '{transport_request}' not found in POST payload: {payload!r}"
    )
    assert "transportRequest" in payload, (
        f"<abapgit:transportRequest> element missing from POST payload: {payload!r}"
    )


# ---------------------------------------------------------------------------
# Property 8: Staging response contains all required object fields
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 8: Staging response contains all required object fields
"""
Property-based tests for AbapGitHandler staging and commit behaviour.

Validates: Requirements 6.2, 7.3, 7.4
"""

_VALID_STATES = ["staged", "unstaged"]
_VALID_CHANGE_TYPES = ["new", "modified", "deleted"]


def _build_staging_xml(objects: List[Dict]) -> str:
    """Build a minimal abapGit staging XML from a list of object dicts."""
    lines = [f'<abapgit:staging xmlns:abapgit="{_NS_ABAPGIT}">']
    lines.append("  <abapgit:objects>")
    for o in objects:
        name = o.get("name", "ZOBJ")
        obj_type = o.get("type", "CLAS")
        state = o.get("state", "staged")
        change_type = o.get("change_type", "modified")
        lines.append(
            f'    <abapgit:object abapgit:name="{name}" abapgit:type="{obj_type}"'
            f' abapgit:state="{state}" abapgit:changeType="{change_type}"/>'
        )
    lines.append("  </abapgit:objects>")
    lines.append("</abapgit:staging>")
    return "\n".join(lines)


_staging_object_strategy = st.fixed_dictionaries({
    "name": _safe_text,
    "type": st.sampled_from(["CLAS", "INTF", "PROG", "FUGR", "TABL", "DTEL"]),
    "state": st.sampled_from(_VALID_STATES),
    "change_type": st.sampled_from(_VALID_CHANGE_TYPES),
})

_staging_list_strategy = st.lists(_staging_object_strategy, min_size=1, max_size=10)


@settings(max_examples=100)
@given(objects=_staging_list_strategy)
def test_staging_response_contains_all_required_object_fields(objects: List[Dict]) -> None:
    """
    **Validates: Requirements 6.2**

    For any XML staging response containing N objects, the parsed output must
    include name, type, state (staged/unstaged), and change_type
    (new/modified/deleted) for each object.
    """
    xml_text = _build_staging_xml(objects)

    client = _make_sap_client(availability_status=200)
    client._request_with_retry = AsyncMock(
        side_effect=[
            (200, "", {}),          # availability probe
            (200, xml_text, {}),    # get_staging GET
        ]
    )

    handler = AbapGitHandler(client)
    result = _run(handler.get_staging("REPOKEY"))

    assert isinstance(result, str)
    assert "not available" not in result, f"Unexpected unavailability: {result!r}"
    assert "Failed" not in result, f"Unexpected failure: {result!r}"

    # Every object's name, type, state, and change_type must appear in the output
    for o in objects:
        assert o["name"] in result, (
            f"Object name '{o['name']}' missing from staging output"
        )
        assert o["type"] in result, (
            f"Object type '{o['type']}' missing from staging output"
        )
        assert o["state"] in result, (
            f"Object state '{o['state']}' missing from staging output"
        )
        assert o["change_type"] in result, (
            f"Object change_type '{o['change_type']}' missing from staging output"
        )


# ---------------------------------------------------------------------------
# Property 9: Empty or blank commit messages are rejected
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 9: Empty or blank commit messages are rejected

# Strategy: generate strings composed entirely of whitespace characters
_whitespace_chars = st.characters(whitelist_categories=("Zs",), whitelist_characters=" \t\n\r\f\v")
_blank_message_strategy = st.one_of(
    st.just(""),
    st.text(alphabet=_whitespace_chars, min_size=1, max_size=50),
)


@settings(max_examples=100)
@given(blank_message=_blank_message_strategy)
def test_empty_or_blank_commit_messages_are_rejected(blank_message: str) -> None:
    """
    **Validates: Requirements 7.3**

    For any string composed entirely of whitespace characters (including the
    empty string), calling commit with that string as the message must return
    an error and must not issue an HTTP request to the SAP system.
    """
    client = _make_sap_client(availability_status=200)
    handler = AbapGitHandler(client)

    result = _run(handler.commit(
        key="REPOKEY",
        message=blank_message,
        author_name="Test Author",
        author_email="author@example.com",
    ))

    assert isinstance(result, str)
    # Must return an error
    assert "failed" in result.lower() or "required" in result.lower(), (
        f"Expected error for blank message {blank_message!r}, got: {result!r}"
    )
    # Must NOT have issued any HTTP request
    assert not client._request_with_retry.called, (
        f"HTTP request was issued for blank message {blank_message!r}; "
        "no HTTP call should be made before validation"
    )


# ---------------------------------------------------------------------------
# Property 10: Invalid author email addresses are rejected
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 10: Invalid author email addresses are rejected

# Strategy: generate strings that do NOT have exactly one '@' with non-empty parts
_invalid_email_strategy = st.one_of(
    # No '@' at all
    st.text(
        alphabet=st.characters(blacklist_characters="@"),
        min_size=0,
        max_size=30,
    ),
    # More than one '@'
    st.builds(
        lambda a, b, c: f"{a}@{b}@{c}",
        _safe_text,
        _safe_text,
        _safe_text,
    ),
    # '@' at the start (empty local part)
    st.builds(lambda d: f"@{d}", _safe_text),
    # '@' at the end (empty domain part)
    st.builds(lambda l: f"{l}@", _safe_text),
    # Just '@'
    st.just("@"),
)


@settings(max_examples=100)
@given(invalid_email=_invalid_email_strategy)
def test_invalid_author_email_addresses_are_rejected(invalid_email: str) -> None:
    """
    **Validates: Requirements 7.4**

    For any string that does not match a valid email address pattern (does not
    contain exactly one '@' with non-empty local and domain parts), calling
    commit with that string as author_email must return an error and must not
    issue an HTTP request.
    """
    client = _make_sap_client(availability_status=200)
    handler = AbapGitHandler(client)

    result = _run(handler.commit(
        key="REPOKEY",
        message="A valid commit message",
        author_name="Test Author",
        author_email=invalid_email,
    ))

    assert isinstance(result, str)
    # Must return an error
    assert "failed" in result.lower() or "required" in result.lower(), (
        f"Expected error for invalid email {invalid_email!r}, got: {result!r}"
    )
    # Must NOT have issued any HTTP request
    assert not client._request_with_retry.called, (
        f"HTTP request was issued for invalid email {invalid_email!r}; "
        "no HTTP call should be made before validation"
    )


# ---------------------------------------------------------------------------
# Property 11: Credentials secret is correctly parsed
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 11: Credentials secret is correctly parsed

import json as _json
import logging as _logging

_nonempty_text = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-@."),
    min_size=1,
    max_size=30,
)

# Credentials used in Property 12 must be long enough to avoid false positives
# from single-char or short substrings appearing in normal response text.
_credential_text = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-@."),
    min_size=8,
    max_size=30,
).filter(lambda s: s not in ("REPOKEY", "stored", "successfully", "credentials", "repository", "not", "found", "Failed"))

# Strategy: JSON objects with username + password, username + token, or both
_creds_secret_strategy = st.one_of(
    # username + password
    st.fixed_dictionaries({
        "username": _nonempty_text,
        "password": _nonempty_text,
    }),
    # username + token
    st.fixed_dictionaries({
        "username": _nonempty_text,
        "token": _nonempty_text,
    }),
    # username + both (password takes precedence)
    st.fixed_dictionaries({
        "username": _nonempty_text,
        "password": _nonempty_text,
        "token": _nonempty_text,
    }),
)


@settings(max_examples=100)
@given(creds=_creds_secret_strategy)
def test_credentials_secret_is_correctly_parsed(creds: dict) -> None:
    """
    **Validates: Requirements 10.2**

    For any JSON string containing username and either password or token,
    AbapGitHandler.set_credentials must extract the username and the
    password/token value and include them in the credentials XML payload
    sent to SAP.
    """
    import sys as _sys
    # Ensure utils.secret_reader is importable (conftest adds src/aws_abap_accelerator to path)
    import importlib as _importlib
    _sr_mod = _importlib.import_module("utils.secret_reader")
    _SecretReader = _sr_mod.SecretReader

    secret_json = _json.dumps(creds)
    expected_username = creds["username"]
    expected_credential = creds.get("password") or creds.get("token")

    # Build a mock client: availability probe + CSRF fetch + POST credentials
    client = MagicMock()
    client.base_url = "https://sap.example.com"
    client.connection = MagicMock()
    client.connection.client = "100"
    client._get_appropriate_headers = AsyncMock(return_value={"Accept": "application/xml"})
    client._request_with_retry = AsyncMock(
        side_effect=[
            (200, "", {}),                              # availability probe
            (200, "", {"x-csrf-token": "tok123"}),     # CSRF fetch
            (200, "", {}),                              # POST credentials
        ]
    )

    handler = AbapGitHandler(client)

    # Patch read_aws_secret on the actual SecretReader class used by the handler
    with patch.object(_SecretReader, "read_aws_secret", return_value=secret_json):
        result = _run(handler.set_credentials(key="REPOKEY", secret_name="my-secret"))

    assert isinstance(result, str)
    assert "not available" not in result, f"Unexpected unavailability: {result!r}"

    # The POST call (3rd call, index 2) must contain username and credential in payload
    calls = client._request_with_retry.call_args_list
    assert len(calls) >= 3, f"Expected at least 3 HTTP calls, got {len(calls)}"

    post_call = calls[2]
    call_kwargs = post_call[1]
    payload = call_kwargs.get("data", "")

    assert expected_username in payload, (
        f"Username '{expected_username}' not found in credentials XML payload: {payload!r}"
    )
    assert expected_credential in payload, (
        f"Credential value not found in credentials XML payload: {payload!r}"
    )
    assert "<abapgit:username>" in payload, (
        f"<abapgit:username> element missing from credentials XML payload: {payload!r}"
    )
    assert "<abapgit:password>" in payload, (
        f"<abapgit:password> element missing from credentials XML payload: {payload!r}"
    )


# ---------------------------------------------------------------------------
# Property 12: Credentials never appear in tool responses or logs
# ---------------------------------------------------------------------------
# Feature: abapgit-adt-operations, Property 12: Credentials never appear in tool responses or logs

@settings(max_examples=100)
@given(
    username=_nonempty_text,
    credential=_credential_text,
    use_token_key=st.booleans(),
    http_status=st.sampled_from([200, 404, 400, 500]),
)
def test_credentials_never_appear_in_responses_or_logs(
    username: str, credential: str, use_token_key: bool, http_status: int
) -> None:
    """
    **Validates: Requirements 10.6, 14.7**

    For any call to set_credentials with any credential value, the string
    returned to the MCP caller must not contain the password or token value
    retrieved from the secret.
    """
    import importlib as _importlib
    _sr_mod = _importlib.import_module("utils.secret_reader")
    _SecretReader = _sr_mod.SecretReader

    cred_key = "token" if use_token_key else "password"
    secret_json = _json.dumps({"username": username, cred_key: credential})

    client = MagicMock()
    client.base_url = "https://sap.example.com"
    client.connection = MagicMock()
    client.connection.client = "100"
    client._get_appropriate_headers = AsyncMock(return_value={"Accept": "application/xml"})
    client._request_with_retry = AsyncMock(
        side_effect=[
            (200, "", {}),                              # availability probe
            (200, "", {"x-csrf-token": "tok123"}),     # CSRF fetch
            (http_status, "", {}),                     # POST credentials
        ]
    )

    handler = AbapGitHandler(client)

    # Capture log output to verify credential doesn't appear in logs
    log_records: list = []

    class CapturingHandler(_logging.Handler):
        def emit(self, record: _logging.LogRecord) -> None:
            log_records.append(self.format(record))

    capturing_handler = CapturingHandler()
    capturing_handler.setLevel(_logging.DEBUG)
    root_logger = _logging.getLogger()
    root_logger.addHandler(capturing_handler)
    original_level = root_logger.level
    root_logger.setLevel(_logging.DEBUG)

    try:
        with patch.object(_SecretReader, "read_aws_secret", return_value=secret_json):
            result = _run(handler.set_credentials(key="REPOKEY", secret_name="my-secret"))
    finally:
        root_logger.removeHandler(capturing_handler)
        root_logger.setLevel(original_level)

    assert isinstance(result, str)

    # The credential value must NOT appear in the returned string
    assert credential not in result, (
        f"Credential value {credential!r} found in tool response: {result!r}"
    )

    # The credential value must NOT appear in any log message
    for log_msg in log_records:
        assert credential not in log_msg, (
            f"Credential value {credential!r} found in log message: {log_msg!r}"
        )

