# Omnivore Highlights Importer

This script imports highlights from an Omnivore export to a Karakeep instance. It matches Omnivore bookmarks to existing Karakeep bookmarks and creates corresponding highlights with position information.

*Note: This tool was developed with assistance from [aider.chat](https://github.com/Aider-AI/aider/).*

## Features

- **Probabilistic bookmark matching**: Uses multiple strategies to match Omnivore bookmarks to Karakeep bookmarks, including exact URL matching, exact title matching, and fuzzy title matching with configurable thresholds
- **Position detection**: Intelligently determines highlight positions within documents using multiple strategies including direct text matching and fuzzy matching algorithms
- **Safe operation**: Only creates new highlights without modifying existing bookmarks or data - all operations are additive and reversible
- **Metadata preservation**: Stores import metadata in each highlight's note field for full traceability and potential cleanup operations
- **Caching**: Caches Karakeep bookmarks locally to avoid repeated API calls during development
- **Progress tracking**: Shows progress bars for long-running operations
- **Dry run mode**: Test the import process without actually creating highlights

## Important Notes

### Safety and Data Integrity

✅ **Database Safety:**
- **Non-destructive**: This script only creates new highlights and never modifies or deletes existing bookmarks or highlights
- **Additive operations**: All changes are purely additive to your Karakeep database
- **Reversible**: Import metadata is stored in each highlight's note field, allowing for easy identification and cleanup if needed
- **No data loss risk**: The import process cannot damage your existing Karakeep data

### Matching Process

🎯 **Probabilistic Matching:**
- **Multi-strategy approach**: Uses exact URL matching, exact title matching, and fuzzy title matching as fallbacks
- **Configurable thresholds**: Fuzzy matching uses a 95% similarity threshold by default, which can be adjusted
- **Best-effort matching**: Some Omnivore bookmarks may not find matches due to title differences or missing URLs
- **Manual review recommended**: Check the console output for unmatched bookmarks that may need manual attention

### Current Limitations

⚠️ **Known Limitations:**
- **PDF highlights not supported**: The script currently skips PDF files by default (`skip_pdf=True`) as PDF highlight positioning is not yet implemented
- **HTML content dependency**: Only works with web page bookmarks that have HTML content available in Karakeep
- **Single highlight color**: All imported highlights use yellow color (can be modified in the code)
- **No duplicate detection**: The script doesn't check if highlights already exist before creating them (relies on user to clean up duplicates if needed)

## Prerequisites

1. **Omnivore Export**: You need a complete Omnivore export containing:
   - `highlights/` directory with `.md` files
   - `content/` directory with `.html` and `.pdf` files  
   - `metadata_*.json` files with bookmark information

2. **Karakeep Instance**: A running Karakeep instance with API access

3. **Environment Setup**: Karakeep API credentials configured via environment variables or parameters

## Installation

Ensure you have the required dependencies installed:

```bash
pip install karakeep-python-api fire tqdm pathlib beautifulsoup4 html2text markdown python-levenshtein
```

## Usage

### Basic Usage (Dry Run)

```bash
python omnivore_highlights_importer.py /path/to/omnivore/export
```

### Actually Import Highlights

```bash
python omnivore_highlights_importer.py /path/to/omnivore/export --dry=False
```

### Include PDF Processing (Experimental)

```bash
python omnivore_highlights_importer.py /path/to/omnivore/export --skip_pdf=False --dry=False
```

### Custom Cache File Location

```bash
python omnivore_highlights_importer.py /path/to/omnivore/export --karakeep_path=./my_bookmarks.temp --dry=False
```

## Parameters

- `omnivore_export_dir` (required): Path to the Omnivore export directory
- `karakeep_path` (optional): Path for caching Karakeep bookmarks (default: `./karakeep_bookmarks.temp`)
- `dry` (optional): If True, simulates the import without creating highlights (default: `True`)
- `skip_pdf` (optional): If True, skips PDF files (default: `True`)

## How It Works

1. **Load Omnivore Data**: Reads metadata files and highlight files from the export
2. **Cache Karakeep Bookmarks**: Fetches all bookmarks from Karakeep (cached locally for performance)
3. **Match Bookmarks**: For each Omnivore highlight file:
   - Finds the corresponding Omnivore bookmark metadata
   - Matches it to a Karakeep bookmark using:
     - Exact URL matching
     - Exact title matching
     - Fuzzy title matching (95% threshold)
4. **Position Detection**: Determines highlight positions using multiple strategies:
   - Direct text matching in plain text
   - Markdown content matching with position scaling
   - Fuzzy matching using Levenshtein distance
   - Link extraction for link-only highlights
5. **Create Highlights**: Creates highlights in Karakeep with calculated positions and stores import metadata in the note field for future reference

## Expected Directory Structure

Your Omnivore export should have this structure:

```
omnivore_export/
├── highlights/
│   ├── article1.md
│   ├── article2.md
│   └── ...
├── content/
│   ├── article1.html
│   ├── article2.pdf
│   └── ...
└── metadata_YYYY-MM-DD_to_YYYY-MM-DD.json
```

## Environment Variables

Set up your Karakeep API credentials:

```bash
export KARAKEEP_PYTHON_API_BASE_URL="https://your-instance.com/api/v1/"
export KARAKEEP_PYTHON_API_KEY="your-api-key"
```

## Highlight Metadata and Cleanup

### Stored Metadata

Each imported highlight includes metadata in its note field containing:
- Original Omnivore bookmark information
- Import timestamp
- Matching strategy used
- Position detection method
- Source file information

This metadata enables:
- **Full traceability** of imported highlights
- **Easy identification** of imported vs. native highlights
- **Batch cleanup operations** if needed
- **Debugging** of matching and positioning issues

### Cleanup Operations

To identify all imported highlights, you can search for highlights containing specific metadata markers in their notes. The metadata format allows for easy filtering and bulk operations if you need to remove imported highlights later.

## Troubleshooting

### Common Issues

1. **"Could not find bookmark"**: The script couldn't match an Omnivore bookmark to a Karakeep bookmark
   - This is normal for some bookmarks due to probabilistic matching
   - Ensure the bookmark exists in Karakeep with similar URL or title
   - Check if URLs or titles match between systems
   - Consider manual import for important unmatched highlights

2. **"No HTML content available"**: The Karakeep bookmark doesn't have HTML content
   - Some bookmarks may not have been fully processed by Karakeep
   - Wait for Karakeep to finish processing the bookmark content
   - Manual content extraction may be needed for complex cases

3. **"Could not match highlight text to corpus"**: The highlight text couldn't be located in the document
   - This may happen with heavily formatted content or dynamic web pages
   - The highlight will be skipped but logged for manual review
   - Consider manual review of problematic highlights

### Performance Notes

- The initial bookmark cache creation can take several minutes for large Karakeep instances
- The cache file is automatically deleted upon successful completion
- Subsequent runs use the cached data for faster processing
- Monitor console output for matching statistics and any issues

## Version

Current version: 0.0.1

## Contributing

This script is part of the karakeep-python-api project. Please report issues or contribute improvements through the main repository.
