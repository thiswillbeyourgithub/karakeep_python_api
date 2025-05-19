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


def get_omnivores_archived(path: str) -> list[dict]:
    # load the data from the omnivore export
    p = Path(path)
    j = p.read_text()
    data: list[dict] = json.loads(j)

    # figure out which should have been archived
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
    omnivore_path: str,
    karakeep_path: Optional[str] = "./karakeep_bookmarks.temp",
    ) -> None:
    archived = get_omnivores_archived(omnivore_path)

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

        assert len(all_bm) == n, f"Only retrieved {len(all_bm)} bookmarks instead of {n}"
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
            if "title" in omnivore and omnivore["title"] and hasattr(content, "title") and content.title:
                if omnivore["title"].lower() == content.title.lower():
                    found_it = True
                    break
                elif ratio(omnivore["title"].lower(), content.title.lower()) >= 0.9:
                    found_it = True
                    breakpoint()
                    break

            if "title" in omnivore and omnivore["title"] and hasattr(bookmark, "title") and bookmark.title:
                if omnivore["title"].lower() == bookmark.title.lower():
                    found_it = True
                    break
                elif ratio(omnivore["title"].lower(), bookmark.title.lower()) >= 0.9:
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
        fresh = karakeep.get_a_single_bookmark(bookmark_id=bookmark.id, include_content=False)
        if fresh.archived:
            tqdm.write(f"Already archived: {url}")
            continue

        # do the archiving
        res_arch = karakeep.update_a_bookmark(
            bookmark_id=bookmark.id,
            update_data={"archived": True},
        )
        if isinstance(res_arch, dict):
            assert res_arch["archived"], res_arch
        else:
            assert res_arch.archived, res_arch
        tqdm.write(f"Succesfuly archived: {url}")


if __name__ == "__main__":
    Fire(main)

