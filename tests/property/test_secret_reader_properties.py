# Feature: abapgit-adt-operations, Property 14: resolve_secret respects priority order
# Feature: abapgit-adt-operations, Property 15: AWS secret values are cached in memory
# Feature: abapgit-adt-operations, Property 13: SecretReader gracefully handles missing AWS SDK or credentials
"""
Property-based tests for SecretReader.

Validates: Requirements 13.5, 13.6, 13.7, 13.8
"""

import os
import sys
from typing import Optional
from unittest.mock import MagicMock, patch, call

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aws_abap_accelerator.utils.secret_reader import SecretReader


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

# Non-empty printable text values (no null bytes — os.environ rejects them)
_value = st.text(
    alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
    min_size=1,
    max_size=64,
)

# Optional value: either a non-empty printable string or None
_opt_value = st.one_of(st.none(), _value)

# Secret / env-var names: alphanumeric + underscore, reasonable length
_name = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
    min_size=1,
    max_size=32,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_resolve(
    secret_name: str,
    env_var_name: str,
    aws_value: Optional[str],
    docker_value: Optional[str],
    env_value: Optional[str],
) -> Optional[str]:
    """
    Call SecretReader.resolve_secret with all three sources controlled via mocks.
    Also clears the AWS cache before each call so tests are independent.
    """
    SecretReader._aws_cache.clear()

    with patch.object(SecretReader, "read_aws_secret", return_value=aws_value), \
         patch.object(SecretReader, "read_secret", return_value=docker_value):
        env_patch: dict = {env_var_name: env_value} if env_value is not None else {}
        with patch.dict(os.environ, env_patch, clear=False):
            # Remove the env var if we want it absent
            if env_value is None and env_var_name in os.environ:
                saved = os.environ.pop(env_var_name)
                try:
                    result = SecretReader.resolve_secret(secret_name, env_var_name)
                finally:
                    os.environ[env_var_name] = saved
            else:
                result = SecretReader.resolve_secret(secret_name, env_var_name)
    return result


# ---------------------------------------------------------------------------
# Property 14: resolve_secret respects priority order
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(
    secret_name=_name,
    env_var_name=_name,
    aws_value=_opt_value,
    docker_value=_opt_value,
    env_value=_opt_value,
)
def test_resolve_secret_priority_order(
    secret_name: str,
    env_var_name: str,
    aws_value: Optional[str],
    docker_value: Optional[str],
    env_value: Optional[str],
) -> None:
    """
    **Validates: Requirements 13.7**

    For every combination of (AWS secret present/absent) × (Docker secret present/absent)
    × (env var present/absent), resolve_secret must return the value from the
    highest-priority source that is present:
      1. AWS Secrets Manager  (highest)
      2. Docker secret
      3. Environment variable
      4. None                 (all absent)
    """
    result = _run_resolve(secret_name, env_var_name, aws_value, docker_value, env_value)

    # Determine expected value according to priority chain
    if aws_value is not None:
        expected = aws_value
    elif docker_value is not None:
        expected = docker_value
    elif env_value is not None:
        expected = env_value
    else:
        expected = None

    assert result == expected, (
        f"resolve_secret({secret_name!r}, {env_var_name!r}) "
        f"with aws={aws_value!r}, docker={docker_value!r}, env={env_value!r} "
        f"returned {result!r}, expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Explicit combinatorial coverage: all 8 combinations
# ---------------------------------------------------------------------------

SENTINEL_AWS = "aws-secret-value"
SENTINEL_DOCKER = "docker-secret-value"
SENTINEL_ENV = "env-var-value"


@pytest.mark.parametrize(
    "aws_value, docker_value, env_value, expected",
    [
        # (aws, docker, env) → expected
        (SENTINEL_AWS,    SENTINEL_DOCKER, SENTINEL_ENV,  SENTINEL_AWS),    # all present → AWS wins
        (SENTINEL_AWS,    SENTINEL_DOCKER, None,          SENTINEL_AWS),    # aws+docker → AWS wins
        (SENTINEL_AWS,    None,            SENTINEL_ENV,  SENTINEL_AWS),    # aws+env → AWS wins
        (SENTINEL_AWS,    None,            None,          SENTINEL_AWS),    # aws only → AWS
        (None,            SENTINEL_DOCKER, SENTINEL_ENV,  SENTINEL_DOCKER), # docker+env → Docker wins
        (None,            SENTINEL_DOCKER, None,          SENTINEL_DOCKER), # docker only → Docker
        (None,            None,            SENTINEL_ENV,  SENTINEL_ENV),    # env only → env
        (None,            None,            None,          None),            # all absent → None
    ],
)
def test_resolve_secret_all_8_combinations(
    aws_value: Optional[str],
    docker_value: Optional[str],
    env_value: Optional[str],
    expected: Optional[str],
) -> None:
    """
    **Validates: Requirements 13.7**

    Explicit parametrised test covering all 8 combinations of source availability.
    """
    result = _run_resolve("my_secret", "MY_ENV_VAR", aws_value, docker_value, env_value)
    assert result == expected, (
        f"aws={aws_value!r}, docker={docker_value!r}, env={env_value!r} "
        f"→ got {result!r}, expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Property 15: AWS secret values are cached in memory
# ---------------------------------------------------------------------------

def _read_aws_secret_with_mock_boto3(secret_name: str, mock_client) -> Optional[str]:
    """
    Call SecretReader.read_aws_secret with boto3 replaced by a mock.
    The mock_client is what boto3.client('secretsmanager') returns.
    """
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client

    # Create mock botocore.exceptions with real Exception subclasses so
    # the except clauses in read_aws_secret work correctly.
    class _FakeClientError(Exception):
        pass

    class _FakeNoCredentialsError(Exception):
        pass

    mock_botocore_exceptions = MagicMock()
    mock_botocore_exceptions.ClientError = _FakeClientError
    mock_botocore_exceptions.NoCredentialsError = _FakeNoCredentialsError

    with patch.dict(sys.modules, {
        "boto3": mock_boto3,
        "botocore": MagicMock(),
        "botocore.exceptions": mock_botocore_exceptions,
    }):
        return SecretReader.read_aws_secret(secret_name)


@settings(max_examples=100)
@given(secret_name=_name, secret_value=_value)
def test_aws_secret_cached_in_memory(secret_name: str, secret_value: str) -> None:
    """
    **Validates: Requirements 13.8**

    For any secret name, calling read_aws_secret twice with the same name must
    result in exactly one call to the AWS Secrets Manager API (the second call
    returns the cached value).
    """
    # Clear cache before each test run to ensure isolation
    SecretReader._aws_cache.clear()

    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": secret_value}

    result1 = _read_aws_secret_with_mock_boto3(secret_name, mock_client)
    # Second call — boto3 mock is no longer active, but the cache should serve the value
    result2 = SecretReader.read_aws_secret.__func__(SecretReader, secret_name)  # type: ignore[attr-defined]

    # Both calls must return the same value
    assert result1 == secret_value, f"First call returned {result1!r}, expected {secret_value!r}"
    assert result2 == secret_value, f"Second call (from cache) returned {result2!r}, expected {secret_value!r}"
    # The boto3 client's get_secret_value must have been called exactly once
    mock_client.get_secret_value.assert_called_once_with(SecretId=secret_name)

    # Cleanup
    SecretReader._aws_cache.clear()


# ---------------------------------------------------------------------------
# Property 13: SecretReader gracefully handles missing AWS SDK or credentials
# ---------------------------------------------------------------------------

@settings(max_examples=100)
@given(secret_name=_name)
def test_read_aws_secret_no_boto3_returns_none(secret_name: str) -> None:
    """
    **Validates: Requirements 13.5**

    When boto3 is not importable, read_aws_secret must return None without
    raising an exception.
    """
    SecretReader._aws_cache.clear()

    # Remove boto3 from sys.modules so the import inside read_aws_secret fails
    with patch.dict(sys.modules, {"boto3": None}):
        result = SecretReader.read_aws_secret(secret_name)

    assert result is None, (
        f"read_aws_secret({secret_name!r}) with boto3 unavailable "
        f"returned {result!r}, expected None"
    )


@settings(max_examples=100)
@given(secret_name=_name)
def test_read_aws_secret_no_credentials_returns_none(secret_name: str) -> None:
    """
    **Validates: Requirements 13.5, 13.6**

    When AWS credentials are not configured (NoCredentialsError), read_aws_secret
    must return None without raising an exception.
    """
    SecretReader._aws_cache.clear()

    class _FakeNoCredentialsError(Exception):
        pass

    class _FakeClientError(Exception):
        pass

    mock_client = MagicMock()
    mock_client.get_secret_value.side_effect = _FakeNoCredentialsError("No credentials")

    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client

    mock_botocore_exceptions = MagicMock()
    mock_botocore_exceptions.ClientError = _FakeClientError
    mock_botocore_exceptions.NoCredentialsError = _FakeNoCredentialsError

    with patch.dict(sys.modules, {
        "boto3": mock_boto3,
        "botocore": MagicMock(),
        "botocore.exceptions": mock_botocore_exceptions,
    }):
        result = SecretReader.read_aws_secret(secret_name)

    assert result is None, (
        f"read_aws_secret({secret_name!r}) with NoCredentialsError "
        f"returned {result!r}, expected None"
    )


@settings(max_examples=100)
@given(secret_name=_name)
def test_read_aws_secret_client_error_returns_none(secret_name: str) -> None:
    """
    **Validates: Requirements 13.6**

    When the secret does not exist or the caller lacks IAM permission (ClientError),
    read_aws_secret must return None without raising an exception.
    """
    SecretReader._aws_cache.clear()

    class _FakeClientError(Exception):
        pass

    class _FakeNoCredentialsError(Exception):
        pass

    mock_client = MagicMock()
    mock_client.get_secret_value.side_effect = _FakeClientError("ResourceNotFoundException")

    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client

    mock_botocore_exceptions = MagicMock()
    mock_botocore_exceptions.ClientError = _FakeClientError
    mock_botocore_exceptions.NoCredentialsError = _FakeNoCredentialsError

    with patch.dict(sys.modules, {
        "boto3": mock_boto3,
        "botocore": MagicMock(),
        "botocore.exceptions": mock_botocore_exceptions,
    }):
        result = SecretReader.read_aws_secret(secret_name)

    assert result is None, (
        f"read_aws_secret({secret_name!r}) with ClientError "
        f"returned {result!r}, expected None"
    )
