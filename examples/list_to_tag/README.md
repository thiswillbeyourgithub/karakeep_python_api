# List to Tag

This script allows you to convert a list into a tag by adding a specified tag to all bookmarks in a specified list.

## Purpose

Sometimes it's useful to "turn a list into a tag" so you can then create more flexible smart lists. For example, if you have a list called "Omnivore Imports", you can tag all those bookmarks with `#omnivore`, then create a smart list with the query `#omnivore -is:archived` to show only unarchived Omnivore bookmarks.

## Usage

```bash
python list_to_tag.py "My List Name" "my-tag"
```

This will:
1. Find the list with the specified name
2. Get all bookmarks from that list  
3. Add the specified tag to each bookmark (skipping any that already have the tag)

## Example

```bash
python list_to_tag.py "Omnivore Imports" "omnivore"
```

After running this, you can create a smart list with query `#omnivore -is:archived` to filter your Omnivore bookmarks by archived status.

---
*This documentation was created with assistance from [aider.chat](https://github.com/Aider-AI/aider/).*
