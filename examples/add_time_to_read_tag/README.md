# Add Time-to-Read Tags

Automatically adds time-to-read tags to your Karakeep bookmarks based on content length.

## What it does

- Analyzes bookmark content (text and HTML) to estimate reading time
- Adds appropriate time tags: `0-5m`, `5-10m`, `10-15m`, `15-30m`, `30m+`
- Removes conflicting time tags to ensure each bookmark has only one time estimate
- Supports both link and text bookmark types
- Uses caching to speed up repeated runs

## Usage

Basic usage with default settings (200 WPM):
```bash
python add_time_to_read_tag.py
```

Customize reading speed:
```bash
python add_time_to_read_tag.py --wpm 250
```

Process all bookmarks (including those already tagged):
```bash
python add_time_to_read_tag.py --reset_all
```

Enable verbose logging:
```bash
python add_time_to_read_tag.py --verbose
```

Use custom cache file location:
```bash
python add_time_to_read_tag.py --cache_file ./my_bookmarks.cache
```

## Options

- `--wpm`: Words per minute reading speed (default: 200)
- `--reset_all`: Process all bookmarks, even those already tagged (default: False)
- `--verbose`: Show debug logs in console (default: False) 
- `--cache_file`: Path to bookmark cache file (default: ./bookmarks.temp)

## Prerequisites

- Karakeep API credentials configured (via environment variables or command line)
- Python packages: `fire`, `tqdm`, `beautifulsoup4`, `loguru`, `karakeep-python-api`

## Behavior

By default, the script skips bookmarks that already have exactly one time tag (assumes they're correct). It only processes:
- Bookmarks with no time tags
- Bookmarks with multiple conflicting time tags

Use `--reset_all` to force reprocessing of all bookmarks.

## Caching

The script caches downloaded bookmarks to speed up repeated runs during testing. Delete the cache file to force a fresh download from the API.

---

*This tool was created with assistance from [aider.chat](https://github.com/Aider-AI/aider/).*
