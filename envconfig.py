"""
Environment configuration utilities for reading configuration parameters and secrets
from environment variables or files.
"""
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

class ConfigError(RuntimeError):
    """Error class for configuration-related issues"""

def read_secret(name: str,
                *,
                default: Optional[str] = None,
                required: bool = False) -> Optional[str]:
    """
    Read a secret from either:
      - <NAME>_FILE: path to a file containing the secret (Docker secret pattern), or
      - <NAME>: a normal environment variable.

    If 'required' is True and nothing is found, raises ConfigError.
    """
    file_var = f"{name}_FILE"

    # 1. If a *_FILE env var is set, read from that file
    path = os.getenv(file_var)
    if path:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except FileNotFoundError as e:
            raise ConfigError(f"Secret file for {name} not found at {path}: {e}") from e
        except OSError as e:
            raise ConfigError(f"Error reading secret file for {name} at {path}: {e}") from e
        if not value and required and default is None:
            raise ConfigError(f"Secret {name} read from file {path} is empty")
        return value or default

    # 2. Fallback: read direct env var
    value = os.getenv(name)
    if value is not None:
        return value

    # 3. Fallback: default or error
    if required and default is None:
        raise ConfigError(f"Required environment variable {name} is not set")
    return default
