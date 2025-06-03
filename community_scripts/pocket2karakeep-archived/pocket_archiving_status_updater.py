"""
Small script made to solve the karakeep issue where Pocket's imported document would not preserve the "archived" value.

This script reads a CSV file exported from Pocket with the following format:
title,url,time_added,tags,status

It identifies entries with status "archive" and updates their status in Karakeep.

"""
import time

from Levenshtein import ratio
import pickle
from fire import Fire
from typing import Optional
from pathlib import Path
import json
import csv
from karakeep_python_api import KarakeepAPI
from tqdm import tqdm

VERSION: str = "1.1.0"

karakeep = KarakeepAPI(verbose=False)


def get_pocket_archived(pocket_export_dir: str) -> list[dict]:
    """
    Loads and parses a CSV file from the specified directory.
    Filters and returns a list of articles that are marked as "archive" in the status column.

    CSV format:
    title,url,time_added,tags,status
    """
    export_dir = Path(pocket_export_dir)
    all_data: list[dict] = []

    # Check if the provided path is a file or directory
    if export_dir.is_file():
        csv_file = export_dir
    else:
        # Look for CSV files in the directory
        csv_files = list(export_dir.glob("*.csv"))
        if not csv_files:
            print(f"Warning: No CSV files found in {pocket_export_dir}.")
            return []
        # Use the first CSV file found
        csv_file = csv_files[0]

    try:
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_data.append(row)
    except Exception as e:
        print(f"Warning: Could not read or process {csv_file.name}: {e}")
        return []

    if not all_data:
        print(f"Warning: No data loaded from {csv_file}.")
        return []

    # Filter for articles with status "archive"
    archived = []
    for d in all_data:
        if d.get("status", "").lower() == "archive":
            # Ensure the dictionary has the required fields
            if "url" not in d:
                print(f"Warning: Entry missing URL: {d}")
                continue

            # Create a dictionary with the expected structure
            archived_entry = {
                "url": d["url"],
                "title": d.get("title", ""),  # Use empty string if title is missing
                "time_added": d.get("time_added", ""),
                "tags": d.get("tags", ""),
                "state": "Archived",  # Add state field for compatibility with the rest of the script
            }
            archived.append(archived_entry)

    return archived


def main(
    pocket_export_dir: str,
    karakeep_path: Optional[str] = "./karakeep_bookmarks.temp",
) -> None:
    archived = get_pocket_archived(pocket_export_dir)

    if not archived:
        print("No archived Pocket articles found or loaded. Exiting.")
        return

    # fetch all the bookmarks from karakeep, as the search feature is unreliable
    # as the loading can be pretty long, we store it to a local file
    if Path(karakeep_path).exists():
        with Path(karakeep_path).open("rb") as f:
            all_bm = pickle.load(f)
    else:
        n = karakeep.get_current_user_stats()["numBookmarks"]
        pbar = tqdm(total=n, desc="Fetching bookmarks")
        all_bm = []
        batch_size = 100  # if you set it too high, you can crash the karakeep instance, 100 being the maximum allowed
        page = karakeep.get_all_bookmarks(
            include_content=False,
            limit=batch_size,
        )
        all_bm.extend(page.bookmarks)
        pbar.update(len(all_bm))
        while page.nextCursor:
            page = karakeep.get_all_bookmarks(
                include_content=False,
                limit=batch_size,
                cursor=page.nextCursor,
            )
            all_bm.extend(page.bookmarks)
            pbar.update(len(page.bookmarks))

        assert (
            len(all_bm) == n
        ), f"Only retrieved {len(all_bm)} bookmarks instead of {n}"
        pbar.close()

        with Path(karakeep_path).open("wb") as f:
            pickle.dump(all_bm, f)

    failed = []
    for pocket in tqdm(archived, desc="Archiving", unit="doc"):
        url = pocket["url"]

        found_it = False
        for bookmark in all_bm:
            found_url = None
            content = bookmark.content
            if hasattr(content, "url"):
                found_url = content.url
            elif hasattr(content, "sourceUrl"):
                found_url = content.sourceUrl
            else:
                found_url = ""



            if found_url == url:
                found_it = True
                break

            # couldn't find a matching url, match by title
            # exact title match:
            if (
                "title" in pocket
                and pocket["title"]
                and hasattr(content, "title")
                and content.title
            ):
                if pocket["title"].lower() == content.title.lower():
                    found_it = True
                    break
            if (
                "title" in pocket
                and pocket["title"]
                and hasattr(bookmark, "title")
                and bookmark.title
            ):
                if pocket["title"].lower() == bookmark.title.lower():
                    found_it = True
                    break

            # fuzzy matching, as a last resort
            threshold = 0.95
            if (
                "title" in pocket
                and pocket["title"]
                and hasattr(content, "title")
                and content.title
            ):
                r = ratio(pocket["title"].lower(), content.title.lower())
                if r >= threshold:
                    found_it = True
                    #breakpoint()
                    break

            if (
                "title" in pocket
                and pocket["title"]
                and hasattr(bookmark, "title")
                and bookmark.title
            ):
                r = ratio(pocket["title"].lower(), bookmark.title.lower())
                if r >= threshold:
                    found_it = True
                    break


        # couldn't be found
        if not found_it:
            failed.append(pocket)
            tqdm.write(f"Failed to find {url}")
            #breakpoint()
            with open("./omnivore_archiver_failed.txt", "a") as f:
                f.write(f"\n{pocket}")
            continue

        # skip already archived
        if bookmark.archived:
            tqdm.write(f"Already archived: {url}")
            continue
        for attempt in range(5):
            try:
                fresh = karakeep.get_a_single_bookmark(bookmark_id=bookmark.id, include_content=False)
                break
            except Exception as e:
                if attempt == 4:
                    raise e
                tqdm.write(f"Get single bookmark failed, retrying ({attempt + 1}/5)")
                time.sleep(1)
        if fresh.archived:
            tqdm.write(f"Already archived: {url}")
            continue

        # do the archiving
        retries = 10
        for attempt in range(retries):
            try:
                res_arch = karakeep.update_a_bookmark(
                    bookmark_id=bookmark.id,
                    update_data={"archived": True},
                )
                break
            except Exception as e:
                if attempt == retries - 1:
                    raise e
                tqdm.write(f"Update failed, retrying ({attempt + 1}/{retries})")
                time.sleep(1)
        if isinstance(res_arch, dict):
            assert res_arch["archived"], res_arch
        else:
            assert res_arch.archived, res_arch
        tqdm.write(f"Succesfuly archived: {url}")


if __name__ == "__main__":
    Fire(main)
