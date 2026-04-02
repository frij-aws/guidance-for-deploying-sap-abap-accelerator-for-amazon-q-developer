"""
Secret reader utility for Docker secrets, environment variables, and AWS Secrets Manager.
Python equivalent of secret-reader.ts
"""

import logging
import os
from pathlib import Path
from typing import Dict, Optional

from .security import sanitize_for_logging

logger = logging.getLogger(__name__)


class SecretReader:
    """Utility class for reading Docker secrets, environment variables, and AWS Secrets Manager"""

    DOCKER_SECRETS_PATH = Path("/run/secrets")

    # Class-level in-memory cache for AWS Secrets Manager values
    _aws_cache: Dict[str, str] = {}
    
    @classmethod
    def read_aws_secret(cls, secret_name: str) -> Optional[str]:
        """
        Retrieve a secret value from AWS Secrets Manager by secret name or ARN.

        Returns the raw secret string (JSON or plain). Returns None on any failure
        (missing SDK, missing credentials, secret not found, insufficient IAM permissions).

        Args:
            secret_name: Secret name or ARN in AWS Secrets Manager

        Returns:
            Secret string value, or None if unavailable
        """
        # Return cached value if available
        if secret_name in cls._aws_cache:
            return cls._aws_cache[secret_name]

        try:
            import boto3  # type: ignore[import]
            from botocore.exceptions import ClientError, NoCredentialsError  # type: ignore[import]
        except ImportError:
            logger.warning(
                "boto3 is not installed; cannot retrieve AWS secret '%s'. "
                "Install boto3 to enable AWS Secrets Manager support.",
                sanitize_for_logging(secret_name),
            )
            return None

        try:
            client = boto3.client("secretsmanager")
            response = client.get_secret_value(SecretId=secret_name)
            # SecretString is present for text secrets; SecretBinary for binary
            value: Optional[str] = response.get("SecretString")
            if value is None:
                logger.warning(
                    "AWS secret '%s' has no SecretString value.",
                    sanitize_for_logging(secret_name),
                )
                return None
            cls._aws_cache[secret_name] = value
            return value
        except NoCredentialsError:
            logger.warning(
                "AWS credentials are not configured; cannot retrieve secret '%s'.",
                sanitize_for_logging(secret_name),
            )
        except ClientError as exc:
            logger.warning(
                "Failed to retrieve AWS secret '%s': %s",
                sanitize_for_logging(secret_name),
                sanitize_for_logging(str(exc)),
            )
        return None

    @classmethod
    def read_secret(cls, secret_name: str) -> Optional[str]:
        """
        Read a Docker secret from the filesystem.
        
        Args:
            secret_name: Name of the secret file
            
        Returns:
            Secret content or None if not found
        """
        try:
            secret_file = cls.DOCKER_SECRETS_PATH / secret_name
            if secret_file.exists() and secret_file.is_file():
                content = secret_file.read_text(encoding='utf-8').strip()
                return content if content else None
        except Exception as e:
            print(f"Warning: Failed to read Docker secret '{sanitize_for_logging(secret_name)}': {sanitize_for_logging(str(e))}")
        
        return None
    
    @classmethod
    def resolve_secret(cls, secret_name: str, env_var_name: str) -> Optional[str]:
        """
        Resolve a secret value using priority order:
          1. AWS Secrets Manager (via ``read_aws_secret``)
          2. Docker secret (via ``read_secret``)
          3. Environment variable

        This method is designed to accommodate additional secret backends in the
        future without changing its signature.

        Args:
            secret_name: Name used for both the AWS secret and the Docker secret file
            env_var_name: Name of the fallback environment variable

        Returns:
            Resolved secret value, or None if not found in any source
        """
        # Priority 1: AWS Secrets Manager
        aws_value = cls.read_aws_secret(secret_name)
        if aws_value is not None:
            return aws_value

        # Priority 2: Docker secret
        docker_value = cls.read_secret(secret_name)
        if docker_value is not None:
            return docker_value

        # Priority 3: Environment variable
        return os.getenv(env_var_name)

    @classmethod
    def get_secret_or_env(cls, secret_name: str, env_var_name: str) -> Optional[str]:
        """
        Deprecated alias for ``resolve_secret``.

        .. deprecated::
            Use :meth:`resolve_secret` instead.
        """
        return cls.resolve_secret(secret_name, env_var_name)
    
    @classmethod
    def list_available_secrets(cls) -> list:
        """
        List all available Docker secrets.
        
        Returns:
            List of secret names
        """
        try:
            if cls.DOCKER_SECRETS_PATH.exists():
                return [f.name for f in cls.DOCKER_SECRETS_PATH.iterdir() if f.is_file()]
        except Exception as e:
            print(f"Warning: Failed to list Docker secrets: {sanitize_for_logging(str(e))}")
        
        return []