"""Removes tags that are attached by AI and have no human attachments."""

import json
import fire
from tqdm import tqdm
from karakeep_python_api import KarakeepAPI

VERSION: str = "1.0.0"


def main(dry_run: bool = False):
    """
    Lists all tags and removes those that are attached by AI and have no human attachments.

    Parameters:
        dry_run: If True, only lists the tags that would be removed without actually removing them
    """
    k = KarakeepAPI()

    # Get all tags
    print("Fetching all tags...")
    tags = k.get_all_tags()
    print(f"Found {len(tags)} tags")

    # Identify tags that are attached by AI and have no human attachments
    ai_only_tags = []
    for tag in tags:
        ai_count = tag.numBookmarksByAttachedType.ai or 0
        human_count = tag.numBookmarksByAttachedType.human or 0

        if ai_count > 0 and human_count == 0:
            ai_only_tags.append(tag)

    print(
        f"Found {len(ai_only_tags)} tags that are attached by AI and have no human attachments"
    )

    # List the tags that will be removed
    if ai_only_tags:
        print("\nTags that will be removed:")
        for tag in ai_only_tags:
            print(
                f"- {tag.name} (ID: {tag.id}, AI attachments: {tag.numBookmarksByAttachedType.ai})"
            )
    else:
        print("No tags to remove")
        return

    # If dry_run is True, don't actually remove the tags
    if dry_run:
        print("\nDRY RUN: No tags were removed")
        return

    # Confirm before removing tags
    confirm = input("\nAre you sure you want to remove these tags? (y/n): ")
    if confirm.lower() != "y":
        print("Operation cancelled")
        return

    # Remove the tags
    print("\nRemoving tags...")
    removed = 0
    for tag in tqdm(ai_only_tags):
        try:
            k.delete_a_tag(tag.id)
            tqdm.write(f"Removed tag: {tag.name} (ID: {tag.id})")
            removed += 1
        except Exception as e:
            tqdm.write(f"Error removing tag {tag.name} (ID: {tag.id}): {str(e)}")

    print(f"\nRemoved {removed} tags out of {len(ai_only_tags)} AI-only tags")


if __name__ == "__main__":
    fire.Fire(main)
