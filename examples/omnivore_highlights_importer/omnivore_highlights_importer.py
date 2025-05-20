import markdown
from Levenshtein import ratio
import re
from typing import Optional
import json
import pickle
from karakeep_python_api import KarakeepAPI
from tqdm import tqdm
from pathlib import Path
from bs4 import BeautifulSoup
from html2text import html2text
import fire

from string_context_matcher import match_highlight_to_corpus

VERSION: str = "0.0.1"


def get_omnivores_bookmarks(omnivore_export_dir: str) -> list[dict]:
    # load and concatenate data from all omnivore export metadata files
    export_path = Path(omnivore_export_dir)
    all_data: list[dict] = []
    
    # Glob for metadata files and sort them to ensure consistent order (e.g., by date if named accordingly)
    metadata_files = sorted(export_path.glob("metadata_*_to_*.json"))
    
    if not metadata_files:
        print(f"Warning: No metadata files matching 'metadata_*_to_*.json' found in {omnivore_export_dir}")
        return []

    for file_path in metadata_files:
        try:
            content = file_path.read_text()
            # Each metadata file is expected to contain a JSON list of bookmarks
            data_from_file: list[dict] = json.loads(content) 
            if isinstance(data_from_file, list):
                all_data.extend(data_from_file)
            else:
                print(f"Warning: Metadata file {file_path.name} does not contain a JSON list. Skipping.")
        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {file_path.name}. Skipping.")
        except Exception as e:
            print(f"Warning: An error occurred while processing {file_path.name}: {e}. Skipping.")
            
    return all_data


def main(
    omnivore_export_dir: str,
    karakeep_path: Optional[str] = "./karakeep_bookmarks.temp",
    dry: bool = True,
) -> None:
    omnivore_export_path = Path(omnivore_export_dir)
    highlights_dir_path = omnivore_export_path / "highlights"
    omnivore_content_dir_path = omnivore_export_path / "content"

    assert omnivore_export_path.exists() and omnivore_export_path.is_dir(), \
        f"Omnivore export directory not found: {omnivore_export_dir}"
    assert highlights_dir_path.exists() and highlights_dir_path.is_dir(), \
        f"Highlights directory not found: {highlights_dir_path}"
    assert omnivore_content_dir_path.exists() and omnivore_content_dir_path.is_dir(), \
        f"Omnivore content directory not found: {omnivore_content_dir_path}"

    highlights_files = [p for p in highlights_dir_path.iterdir() if p.name.endswith(".md") and p.read_text().strip()]
    content_files: dict = {p.stem: p.suffix for p in omnivore_content_dir_path.iterdir()}

    data = get_omnivores_bookmarks(omnivore_export_dir)

    karakeep = KarakeepAPI(verbose=False)

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
            include_content=True,
            limit=batch_size,
        )
        all_bm.extend(page.bookmarks)
        pbar.update(len(all_bm))
        while page.nextCursor:
            page = karakeep.get_all_bookmarks(
                include_content=True,
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

    for f in tqdm(highlights_files, unit="highlight", desc="importing highlights"):
        name = f.stem

        highlights = f.read_text().strip().split("\n> ")
        highlights = [h.strip() for h in highlights if h.strip()]
        if not highlights:
            continue

        found_omni = False
        for omnivore in data:
            if omnivore["slug"] == name:
                found_omni = True
                break

        if not found_omni:
            print("Couldn't find the omnivore 'bookmark' for that highlight")
            breakpoint()
        url = omnivore["url"]

        # check if the highlight is from a pdf or an html
        if name not in content_files:
            breakpoint()
        if content_files[name] == ".pdf":
            is_pdf = True
        elif content_files[name] == ".html":
            is_pdf = False
        else:
            print("Is neither a webpage nor a pdf?!")
            breakpoint()


        found_bm = False
        for bookmark in all_bm:
            found_url = None
            content = bookmark.content

            if is_pdf:
                breakpoint()

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
                found_bm = True
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
                    found_bm = True
                    break
            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(bookmark, "title")
                and bookmark.title
            ):
                if omnivore["title"].lower() == bookmark.title.lower():
                    found_bm = True
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
                    found_bm = True
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
                    found_bm = True
                    breakpoint()
                    break

        if not found_bm:
            print("Did not find the bookmark")
            breakpoint()

        kara_content = bookmark.content.htmlContent

        as_md = html2text(kara_content, bodywidth=9999999)

        as_text = BeautifulSoup(kara_content).get_text()

        for highlight in highlights:

            if highlight.startswith("> "):
                highlight = highlight[1:]
                highlight.strip()

            high_as_text = BeautifulSoup(markdown.markdown(highlight)).get_text()
            if high_as_text in as_text:
                start = as_text.index(high_as_text)
            elif highlight in as_md:
                start = int(as_md.index(highlight) / len(as_md) * len(as_text))
            else:
                match_text = match_highlight_to_corpus(query=high_as_text, corpus=as_text)
                match_md = match_highlight_to_corpus(query=highlight, corpus=as_md)
                breakpoint()

            end = start + len(high_as_text)

            if not dry:
                resp = karakeep.create_a_new_highlight(
                    highlight_data={
                        "bookmarkId": bookmark.id,
                        "text": high_as_text,
                        "color": "yellow",
                        "note": f"By omnivore_highlights_importer.py version {VERSION}",
                        "startOffset": start,
                        "endOffset": end,
                    }
                )
                assert resp, highlight


if __name__ == "__main__":
    fire.Fire(main)
