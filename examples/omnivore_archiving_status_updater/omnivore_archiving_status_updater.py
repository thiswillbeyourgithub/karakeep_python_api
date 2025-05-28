"""
Small script made to solve the karakeep issue where Omnivore's imported document would not preserve the "archived" value.

Link: https://github.com/karakeep-app/karakeep/issues/703

"""

from Levenshtein import ratio
import pickle
from typing import Optional
from fire import Fire
from pathlib import Path
import json
from karakeep_python_api import KarakeepAPI
from tqdm import tqdm

karakeep = KarakeepAPI(verbose=False)


def get_omnivores_archived(omnivore_export_dir: str) -> list[dict]:
    """
    Loads and concatenates all Omnivore metadata JSON files from the specified directory.
    Filters and returns a list of articles that are marked as "Archived".
    """
    export_dir = Path(omnivore_export_dir)
    all_data: list[dict] = []

    # Find all metadata_*.json files, load, and concatenate their lists
    for json_file in export_dir.glob("metadata_*_to_*.json"):
        try:
            content = json_file.read_text()
            data: list[dict] = json.loads(content)
            all_data.extend(data)
        except json.JSONDecodeError as e:
            print(f"Warning: Could not decode JSON from {json_file.name}: {e}")
        except Exception as e:
            print(f"Warning: Could not read or process {json_file.name}: {e}")

    if not all_data:
        print(
            f"Warning: No data loaded from {omnivore_export_dir}. Ensure 'metadata_*_to_*.json' files exist and are valid."
        )
        return []

    # figure out which should have been archived
    data = all_data  # Use the concatenated data
    active = []
    archived = []
    unknown = []
    for d in data:
        if d["state"] == "Archived":
            archived.append(d)
        elif d["state"] == "Active":
            active.append(d)
        elif d["state"] == "Unknown":
            unknown.append(d)
        else:
            breakpoint()
    return archived


def main(
    omnivore_export_dir: str,
    karakeep_path: Optional[str] = "./karakeep_bookmarks.temp",
) -> None:
    archived = get_omnivores_archived(omnivore_export_dir)

    if not archived:
        print("No archived Omnivore articles found or loaded. Exiting.")
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
    for omnivore in tqdm(archived, desc="Archiving", unit="doc"):
        url = omnivore["url"]

        found_it = False
        for bookmark in all_bm:
            found_url = None
            content = bookmark.content
            if hasattr(content, "url"):
                found_url = content.url
            elif hasattr(content, "sourceUrl"):
                found_url = content.sourceUrl
            else:
                breakpoint()

            # handling local PDF, they don't have proper url
            if found_url and found_url.startswith("https://omnivore.app"):
                found_url = None

            if found_url == url:
                found_it = True
                break

            # couldn't find a matching url, match by title
            # exact title match:
            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(content, "title")
                and content.title
            ):
                if omnivore["title"].lower() == content.title.lower():
                    found_it = True
                    break
            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(bookmark, "title")
                and bookmark.title
            ):
                if omnivore["title"].lower() == bookmark.title.lower():
                    found_it = True
                    break

            # fuzzy matching, as a last resort
            threshold = 0.95
            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(content, "title")
                and content.title
            ):
                r = ratio(omnivore["title"].lower(), content.title.lower())
                if r >= threshold:
                    found_it = True
                    breakpoint()
                    break

            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(bookmark, "title")
                and bookmark.title
            ):
                r = ratio(omnivore["title"].lower(), bookmark.title.lower())
                if r >= threshold:
                    found_it = True
                    breakpoint()
                    break

        # couldn't be found
        if not found_it:
            failed.append(omnivore)
            tqdm.write(f"Failed to find {url}")
            breakpoint()
            with open("./omnivore_archiver_failed.txt", "a") as f:
                f.write(f"\n{omnivore}")
            continue

        # skip already archived
        if bookmark.archived:
            tqdm.write(f"Already archived: {url}")
            continue
        fresh = karakeep.get_a_single_bookmark(
            bookmark_id=bookmark.id, include_content=False
        )
        if fresh.archived:
            tqdm.write(f"Already archived: {url}")
            continue

        # do the archiving
        res_arch = karakeep.update_a_bookmark(
            bookmark_id=bookmark.id,
            update_data={"archived": True},
        )
        assert res_arch["archived"], res_arch
        tqdm.write(f"Succesfuly archived: {url}")


if __name__ == "__main__":
    Fire(main)
