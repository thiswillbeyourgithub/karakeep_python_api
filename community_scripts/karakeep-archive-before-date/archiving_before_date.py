"""
Small script to clean old article not archived after an import from another readlater app.

Parameters:
    before_date: Date in YYYY-MM-DD format. Articles created before this date will be archived.
"""

import time
from datetime import datetime

from Levenshtein import ratio
import pickle
from fire import Fire
from typing import Optional
from pathlib import Path
import json
import csv
from karakeep_python_api import KarakeepAPI
from tqdm import tqdm

VERSION: str = "1.0.0"

karakeep = KarakeepAPI(verbose=False)


def main(before_date: str) -> None:
    """Archive articles created before the specified date.

    Args:
        before_date: Date string in YYYY-MM-DD format
    """
    before_date = datetime.strptime(before_date, "%Y-%m-%d")

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

    assert len(all_bm) == n, f"Only retrieved {len(all_bm)} bookmarks instead of {n}"
    pbar.close()

    failed = []
    for bookmark in all_bm:
        # skip already archived
        if bookmark.archived:
            continue

        # tqdm.write(f"Creation Date: {bookmark.createdAt}")
        creation_date = datetime.strptime(bookmark.createdAt, "%Y-%m-%dT%H:%M:%S.%fZ")

        if creation_date > before_date:
            continue

        # do the archiving
        retries = 3
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
        tqdm.write(f"Successfuly archived: {bookmark.title}")


if __name__ == "__main__":
    Fire(main)
