# Karakeep Archive before date

Small cleaning script to clean old article not archived after an import from another readlater app.

## Prerequisites

N/A 

## Usage

Define a date to limit archiving. All not archived bookmarks before this date will be archived. 

```bash
python archiving_before_date.py --before-date 2023-12-24
```

`--before-date` format is `YYYY-MM-DD`

You might need to set up environment variables for the Karakeep API client or pass them as arguments if the script supports it (e.g., `KARAKEEP_PYTHON_API_BASE_URL` and `KARAKEEP_PYTHON_API_KEY`). Refer to the script's help or the `karakeep-python-api` documentation for more details on authentication.



