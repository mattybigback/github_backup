# Github Local Backup
Creates a local backup of all rewpositories in a Github account.

## Requirements
A requirements.txt file is provided for use with pip.

## Environment Variables

This project is configured entirely via environment variables (optionally loaded from a local `.env` file) and/or "secret files" referenced by `*_FILE` variables.

The helper `read_secret` in `envconfig.py` looks up a value in this order for a given name `NAME`:

1. If `NAME_FILE` is set, it treats the value as a path and reads the secret from that file.
2. Otherwise, it falls back to the plain `NAME` environment variable.
3. If neither is set, it uses the provided default (if any) or raises a configuration error when the value is required.

This means you can either set values directly as environment variables or point to files that contain the secret values (recommended for production/container use).

### Environment variables and secrets

| Name                      | Alternate `*_FILE`            | Required | Default Value   | Description |
|---------------------------|-------------------------------|----------|-----------------|-------------|
| `GITHUB_APP_ID`           | `GITHUB_APP_ID_FILE`          | Yes      | —               | GitHub App ID for the GitHub App used to access repositories. |
| `GITHUB_INSTALLATION_ID`  | `GITHUB_INSTALLATION_ID_FILE` | Yes      | —               | Installation ID of the GitHub App on the target account/organisation. |
| `GITHUB_PK`               | `GITHUB_PK_FILE`              | Yes      | —               | PEM-encoded private key for the GitHub App, used to sign JWTs. |
| `GH_ARCHIVE_ZIP_PATH`     | `GH_ARCHIVE_ZIP_PATH_FILE`    | No       | `./backup_zips` | Directory where generated backup ZIP archives are stored. |
| `GH_ARCHIVE_ZIP_PREFIX`   | `GH_ARCHIVE_ZIP_PREFIX_FILE`  | No       | `Github_Backup_`| Filename prefix for generated backup archives. |

An example .env file is provided.

When running in Docker or another container platform, you can instead mount secrets to UTF8-encoded text files, and set the corresponding `*_FILE` variables to point at them.
