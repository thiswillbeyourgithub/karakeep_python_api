# Omnivore2Karakeep-archived

This script addresses an issue in Karakeep (as of version 0.24.1) where the "archived" status of bookmarks imported from Omnivore is not preserved. See [karakeep issue #703](https://github.com/karakeep-app/karakeep/issues/703) for more details.

This tool reads your Omnivore export data and updates the corresponding bookmarks in your Karakeep instance to reflect their original "archived" status.

## Prerequisites

1.  **Omnivore Export Directory**: You need to have an export of your Omnivore data. This should be a directory containing the `metadata_X_to_Y.json` files provided by Omnivore. The script will automatically find and process all such files within the specified directory.

## Usage

Ensure you have your Omnivore export directory ready. Then, run the script:

```bash
python omnivore2karakeep-archived.py --omnivore-export-dir /path/to/your/omnivore_export_directory
```

You might need to set up environment variables for the Karakeep API client or pass them as arguments if the script supports it (e.g., `KARAKEEP_PYTHON_API_BASE_URL` and `KARAKEEP_PYTHON_API_KEY`). Refer to the script's help or the `karakeep-python-api` documentation for more details on authentication.

The script will:
1. Scan the specified Omnivore export directory for `metadata_*_to_*.json` files.
2. Load and combine data from all found JSON files to identify articles that should be "Archived".
3. Fetch all bookmarks from your Karakeep instance. (This can take a while and is cached locally in `karakeep_bookmarks.temp` by default to speed up subsequent runs).
4. For each Omnivore article marked as "Archived", it will find the corresponding bookmark in Karakeep (matching by URL or title) and update its status to "archived" if it's not already.

---
This tool was developed with assistance from [aider.chat](https://github.com/Aider-AI/aider/).
