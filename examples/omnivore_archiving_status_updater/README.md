# Omnivore Archiving Status Updater for Karakeep

This script addresses an issue in Karakeep (as of version 0.24.1) where the "archived" status of bookmarks imported from Omnivore is not preserved. See [karakeep issue #703](https://github.com/karakeep-app/karakeep/issues/703) for more details.

This tool reads your Omnivore export data and updates the corresponding bookmarks in your Karakeep instance to reflect their original "archived" status.

## Prerequisites

1.  **Omnivore Export**: You need to have an export of your Omnivore data. Omnivore typically exports data in several `metadata_X_to_Y.json` files.
2.  **Concatenate Omnivore JSON files**: Before running the script, you must concatenate all your `metadata_X_to_Y.json` files from the Omnivore export into a single `concatenated.json` file. You can use a command-line tool like `jq` for this. For example, navigate to the directory containing your Omnivore JSON files and run:

    ```bash
    jq -s 'add' *.json > concatenated.json
    ```

    Alternatively, other tools or scripts can be used to achieve the same result of merging the JSON arrays into one.

## Usage

Once you have your `concatenated.json` file, you can run the script:

```bash
python omnivore_archiving_status_updater.py --omnivore-path /path/to/your/concatenated.json
```

You might need to set up environment variables for the Karakeep API client or pass them as arguments if the script supports it (e.g., `KARAKEEP_PYTHON_API_BASE_URL` and `KARAKEEP_PYTHON_API_KEY`). Refer to the script's help or the `karakeep-python-api` documentation for more details on authentication.

The script will:
1. Read the Omnivore `concatenated.json` file to identify articles that should be archived.
2. Fetch all bookmarks from your Karakeep instance. (This can take a while and is cached locally in `karakeep_bookmarks.temp` by default to speed up subsequent runs).
3. For each Omnivore article marked as "Archived", it will find the corresponding bookmark in Karakeep (matching by URL or title) and update its status to "archived" if it's not already.

---
This tool was developed with assistance from [aider.chat](https://github.com/Aider-AI/aider/).
