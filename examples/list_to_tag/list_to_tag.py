"""Adds a specified tag to all bookmarks in a specified list."""

import json
import fire
from tqdm import tqdm
from karakeep_python_api import KarakeepAPI


def main(list_name: str, tag_to_add: str):
    """
    Adds a specified tag to all bookmarks in a specified list.
    
    Parameters:
        list_name: Name of the list to get bookmarks from
        tag_to_add: Name of the tag to add to bookmarks
    """
    k = KarakeepAPI()

    # Get all lists and find the one with the specified name
    lists = k.get_all_lists()
    target_list = None
    for l in lists:
        if l.name == list_name:
            target_list = l
            break
    
    if not target_list:
        print(f"List '{list_name}' not found")
        return
    
    list_id = target_list.id

    # Get all bookmarks from the list
    bookmarks = []
    cursor = None
    while True:
        page = k.get_bookmarks_in_the_list(
            list_id=list_id,
            include_content=False,
            limit=50,
            cursor=cursor
        )
        cursor = page.nextCursor
        new = page.bookmarks
        if not new:
            print("No new bookmarks")
            break
        bookmarks.extend(new)
        print(f"Added {len(new)} bookmarks, total is {len(bookmarks)}")
        if not cursor:
            print("No cursor")
            break

    # Add tag to bookmarks that don't already have it
    skipped = 0
    added = 0
    for b in tqdm(bookmarks):
        # Check if bookmark already has the tag
        existing_tag_names = [tag.name for tag in b.tags] if b.tags else []
        if tag_to_add in existing_tag_names:
            tqdm.write(f"Skipping bookmark {b.id} - already has tag '{tag_to_add}'")
            skipped += 1
            continue
            
        out = k.attach_tags_to_a_bookmark(
            bookmark_id=b.id,
            tag_names=[tag_to_add],
        )
        tqdm.write(f"Title: '{b.title}'  Answer: '{json.dumps(out)}'")
        added += 1
    
    print(f"Added tag '{tag_to_add}' to {added} bookmarks, skipped {skipped} bookmarks that already had the tag")


if __name__ == "__main__":
    fire.Fire(main)
