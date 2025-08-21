# Karakeep-Remove-AI-Tags

This script allows you to identify and remove tags that were attached by AI and have no human attachments.

## Purpose

Karakeep can automatically tag bookmarks using AI. Sometimes, you may want to clean up tags that were only added by AI and not by humans. This script helps you identify and remove such tags.

## Usage

```bash
python karakeep-remove-ai-tags.py [--dry-run]
```

### Parameters

- `--dry-run`: Optional. If provided, the script will only list the tags that would be removed without actually removing them.

## What the script does

This script will:
1. Fetch all tags from your Karakeep account
2. Identify tags that are attached by AI and have no human attachments
3. List these tags with their IDs and the number of AI attachments
4. If not in dry-run mode, ask for confirmation before removing the tags
5. Remove the confirmed tags

## Examples

### Dry run (preview only)

```bash
python karakeep-remove-ai-tags.py --dry-run
```

This will list all tags that would be removed without actually removing them.

### Remove AI-only tags

```bash
python karakeep-remove-ai-tags.py
```

This will list all tags that are attached by AI and have no human attachments, ask for confirmation, and then remove the confirmed tags.

---
*This documentation was created with assistance from AI.*
