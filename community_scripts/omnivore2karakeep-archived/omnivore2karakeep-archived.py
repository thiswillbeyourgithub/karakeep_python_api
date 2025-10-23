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
from loguru import logger

# Configure loguru to log debug messages to a local file
logger.add("omniore2karakeep-archived.log", level="DEBUG", rotation="10 MB")

karakeep = KarakeepAPI(verbose=False)

VERSION: str = "2.0.0"


def match_omnivore_to_bookmark(omnivore: dict, bookmark) -> tuple[bool, float]:
    """
    Determines if an Omnivore article matches a Karakeep bookmark.

    Uses URL matching first, then title matching (exact and fuzzy).

    Parameters:
    - omnivore: Omnivore article dictionary
    - bookmark: Karakeep bookmark object

    Returns:
    - tuple[bool, float]: (is_match, ratio) where ratio is 1.0 for exact matches
      and Levenshtein ratio for fuzzy matches
    """
    url = omnivore["url"]

    # Try URL matching first
    found_url = None
    content = bookmark.content
    if hasattr(content, "url"):
        found_url = content.url
    elif hasattr(content, "sourceUrl"):
        found_url = content.sourceUrl
    else:
        raise ValueError(content)

    # handling local PDF, they don't have proper url
    if found_url and found_url.startswith("https://omnivore.app"):
        found_url = None

    if found_url == url:
        return True, 1.0

    # couldn't find a matching url, match by title
    # exact title match:
    if (
        "title" in omnivore
        and omnivore["title"]
        and hasattr(content, "title")
        and content.title
    ):
        if omnivore["title"].lower() == content.title.lower():
            return True, 1.0
    if (
        "title" in omnivore
        and omnivore["title"]
        and hasattr(bookmark, "title")
        and bookmark.title
    ):
        if omnivore["title"].lower() == bookmark.title.lower():
            return True, 1.0

    # fuzzy matching, as a last resort
    threshold = 0.95
    best_ratio = 0.0

    if (
        "title" in omnivore
        and omnivore["title"]
        and hasattr(content, "title")
        and content.title
    ):
        r = ratio(omnivore["title"].lower(), content.title.lower())
        best_ratio = max(best_ratio, r)

    if (
        "title" in omnivore
        and omnivore["title"]
        and hasattr(bookmark, "title")
        and bookmark.title
    ):
        r = ratio(omnivore["title"].lower(), bookmark.title.lower())
        best_ratio = max(best_ratio, r)

    if best_ratio >= threshold:
        return True, best_ratio

    return False, best_ratio


def get_omnivores_archived(
    omnivore_export_dir: str,
    read_threshold: int = 80,
    treat_read_as_archived: bool = True,
) -> list[dict]:
    """
    Loads and concatenates all Omnivore metadata JSON files from the specified directory.
    Filters and returns a list of articles that are marked as "Archived".

    Parameters:
    - read_threshold: Reading progress percentage threshold to consider an article as "read" (default: 80)
    - treat_read_as_archived: If True, treat articles above read_threshold as archived (default: True)
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
            logger.warning(f"Could not decode JSON from {json_file.name}: {e}")
        except Exception as e:
            logger.warning(f"Could not read or process {json_file.name}: {e}")

    if not all_data:
        logger.warning(
            f"No data loaded from {omnivore_export_dir}. Ensure 'metadata_*_to_*.json' files exist and are valid."
        )
        return []

    # figure out which should have been archived
    data = all_data  # Use the concatenated data
    active = []
    archived = []
    read = []
    unknown = []
    for d in data:
        if int(d["readingProgress"]) > read_threshold:
            read.append(d)
        if d["state"] == "Archived":
            archived.append(d)
        elif d["state"] == "Active":
            active.append(d)
        elif d["state"] == "Unknown":
            unknown.append(d)
        else:
            raise ValueError(json.dumps(d))

    # If treat_read_as_archived is True, add read articles to archived list (avoiding duplicates)
    if treat_read_as_archived:
        archived_urls = {
            d["url"] for d in archived
        }  # Create set of already archived URLs
        for read_article in read:
            if read_article["url"] not in archived_urls:
                archived.append(read_article)

    return archived


def main(
    omnivore_export_dir: str,
    karakeep_temp_path: Optional[str] = "./karakeep_bookmarks.temp",
    read_threshold: int = 80,
    treat_read_as_archived: bool = True,
) -> None:
    assert Path(omnivore_export_dir).exists(), "Omnivore export dir does not exist"
    assert Path(omnivore_export_dir).is_dir(), "Omnivore export dir is not a dir"
    archived = get_omnivores_archived(
        omnivore_export_dir, read_threshold, treat_read_as_archived
    )

    if not archived:
        logger.info("No archived Omnivore articles found or loaded. Exiting.")
        return

    # fetch all the bookmarks from karakeep, as the search feature is unreliable
    # as the loading can be pretty long, we store it to a local file
    if Path(karakeep_temp_path).exists():
        with Path(karakeep_temp_path).open("rb") as f:
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

        assert len(all_bm) == n, (
            f"Only retrieved {len(all_bm)} bookmarks instead of {n}"
        )
        pbar.close()

        with Path(karakeep_temp_path).open("wb") as f:
            pickle.dump(all_bm, f)

    failed = []
    for omnivore in tqdm(archived, desc="Archiving", unit="doc"):
        url = omnivore["url"]

        # Collect all potential matches with their ratios
        potential_matches = []
        for bookmark in all_bm:
            is_match, match_ratio = match_omnivore_to_bookmark(omnivore, bookmark)
            if is_match:
                potential_matches.append((bookmark, match_ratio))

        # couldn't be found
        if not potential_matches:
            failed.append(omnivore)
            tqdm.write(f"Failed to find {url}")
            with open("./omnivore_archiver_failed.txt", "a") as f:
                f.write(f"\n{omnivore}")
            continue

        # Choose the bookmark with the highest ratio
        bookmark = max(potential_matches, key=lambda x: x[1])[0]

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

    # Clean up the temporary file since everything worked successfully
    if Path(karakeep_temp_path).exists():
        Path(karakeep_temp_path).unlink()


if __name__ == "__main__":
    Fire(main)
