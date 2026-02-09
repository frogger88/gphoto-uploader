# Google Photos Transfer Tool

**Author:** Gemini 3 Flash

A Python-based GUI application to transfer photos and videos from a local Google Takeout archive (or any folder of images) to a new Google Photos account. This tool recreates your original folder structures as albums and ensures a resilient migration process.

## Features

- **Recreate Albums**: Automatically detects sub-folders and creates corresponding albums in the target account.
- **Duplicate Prevention**: Uses an SQLite database to track uploaded files, preventing re-uploads if the process is interrupted.
- **Resilient Resumption**: Safely stop and resume large migrations; the tool picks up exactly where it left off.
- **User-Friendly GUI**: Simple interface for selecting sources, managing a transfer queue, and monitoring progress.
- **Detailed Logging**: Every transfer is recorded with timestamps for easy verification.

## Prerequisites

- Python 3.7+
- A Google Cloud Project with the Google Photos Library API enabled.
- OAuth 2.0 credentials (`client_secret.json`).

## Disclaimer

This tool is provided "as is" without warranty of any kind. Users are responsible for their own data and should verify their backups before proceeding.
