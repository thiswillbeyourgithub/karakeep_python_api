import re
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


def find_highlight_position(
    high_as_text: str,
    highlight: str,
    as_text: str,
    as_md: str,
    kara_content: str
) -> tuple[int, int]:
    """
    Find the start and end positions of a highlight within the document content.
    
    This function uses multiple strategies to locate highlights:
    1. Direct text matching in plain text
    2. Markdown content matching with position scaling
    3. Fuzzy matching using string context matcher
    4. Link extraction for highlights containing only links
    
    Parameters
    ----------
    high_as_text : str
        The highlight text converted to plain text
    highlight : str
        The original highlight text (may contain markdown/HTML)
    as_text : str
        The full document content as plain text
    as_md : str
        The full document content as markdown
    kara_content : str
        The raw HTML content of the document
        
    Returns
    -------
    tuple[int, int]
        A tuple containing (start_position, end_position) of the highlight
    """
    start = 0
    
    # Strategy 1: Direct text matching
    if high_as_text in as_text:
        start = as_text.index(high_as_text)

    # Strategy 2: Markdown content matching with position scaling
    if highlight in as_md:
        if start == 0:
            start = int(as_md.index(highlight) / len(as_md) * len(as_text))
        else:
            start = (
                start + int(as_md.index(highlight) / len(as_md) * len(as_text))
            ) // 2

    # Strategy 3: Fuzzy matching when direct matching fails
    if start == 0:
        match_text = match_highlight_to_corpus(
            query=high_as_text, corpus=as_text
        )
        match_md = match_highlight_to_corpus(query=highlight, corpus=as_md)

        if match_text.matches and match_md.matches:
            position_text = as_text.index(match_text.matches[0]) / len(as_text)
            position_md = as_md.index(match_md.matches[0]) / len(as_md)
            diff = abs(position_text - position_md)

            if diff >= 0.20:
                # if differ too much, assume html has a too large overhead
                rel_pos = position_md
            else:
                rel_pos = (position_text + position_md) / 2
            del diff
        elif match_text.matches:
            rel_pos = as_text.index(match_text.matches[0]) / len(as_text)
        elif match_md.matches:
            rel_pos = as_md.index(match_md.matches[0]) / len(as_md)
        elif (
            not high_as_text
        ):  # probably contains only a link, so we have to find that link in the raw html
            links = re.findall(
                r"\bhttp:\/\/[-\w+&@#\/%?=~()|!:,.;]*[-\w+&@#\/%=~()|]",
                highlight,
            )
            positions = [
                kara_content.index(link)
                for link in links
                if link in kara_content
            ]
            assert positions, highlight
            rel_pos = int(sum(positions) / len(positions))
        else:
            raise ValueError(
                f"Could not match highlight text to corpus for highlight: {highlight[:100]}{'...' if len(highlight) > 100 else ''}"
            )
        start = int(rel_pos * len(high_as_text))
        del rel_pos

    end = start + len(high_as_text)
    return start, end


def load_bookmarks_from_karakeep(karakeep: KarakeepAPI, karakeep_path: str) -> list:
    """
    Load all bookmarks from Karakeep API, using local cache if available.
    
    This function fetches all bookmarks from the Karakeep instance, with content included.
    To avoid repeated API calls during development, bookmarks are cached locally.
    
    Parameters
    ----------
    karakeep : KarakeepAPI
        The Karakeep API client instance
    karakeep_path : str
        Path to the local cache file for storing bookmarks
        
    Returns
    -------
    list
        List of all bookmarks from the Karakeep instance
    """
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
    
    return all_bm


def get_omnivores_bookmarks(omnivore_export_dir: str) -> list[dict]:
    # load and concatenate data from all omnivore export metadata files
    export_path = Path(omnivore_export_dir)
    all_data: list[dict] = []

    # Glob for metadata files and sort them to ensure consistent order (e.g., by date if named accordingly)
    metadata_files = sorted(export_path.glob("metadata_*_to_*.json"))

    if not metadata_files:
        print(
            f"Warning: No metadata files matching 'metadata_*_to_*.json' found in {omnivore_export_dir}"
        )
        return []

    for file_path in metadata_files:
        try:
            content = file_path.read_text()
            # Each metadata file is expected to contain a JSON list of bookmarks
            data_from_file: list[dict] = json.loads(content)
            if isinstance(data_from_file, list):
                all_data.extend(data_from_file)
            else:
                print(
                    f"Warning: Metadata file {file_path.name} does not contain a JSON list. Skipping."
                )
        except json.JSONDecodeError:
            print(f"Warning: Could not decode JSON from {file_path.name}. Skipping.")
        except Exception as e:
            print(
                f"Warning: An error occurred while processing {file_path.name}: {e}. Skipping."
            )

    return all_data


def main(
    omnivore_export_dir: str,
    karakeep_path: Optional[str] = "./karakeep_bookmarks.temp",
    dry: bool = True,
    skip_pdf: bool = True,
) -> None:
    omnivore_export_path = Path(omnivore_export_dir)
    highlights_dir_path = omnivore_export_path / "highlights"
    omnivore_content_dir_path = omnivore_export_path / "content"

    assert (
        omnivore_export_path.exists() and omnivore_export_path.is_dir()
    ), f"Omnivore export directory not found: {omnivore_export_dir}"
    assert (
        highlights_dir_path.exists() and highlights_dir_path.is_dir()
    ), f"Highlights directory not found: {highlights_dir_path}"
    assert (
        omnivore_content_dir_path.exists() and omnivore_content_dir_path.is_dir()
    ), f"Omnivore content directory not found: {omnivore_content_dir_path}"

    highlights_files = [
        p
        for p in highlights_dir_path.iterdir()
        if p.name.endswith(".md") and p.read_text().strip()
    ]
    content_files: dict = {
        p.stem: p.suffix for p in omnivore_content_dir_path.iterdir()
    }

    data = get_omnivores_bookmarks(omnivore_export_dir)

    karakeep = KarakeepAPI(verbose=False)

    # fetch all the bookmarks from karakeep, as the search feature is unreliable
    # as the loading can be pretty long, we store it to a local file
    all_bm = load_bookmarks_from_karakeep(karakeep, karakeep_path)

    for f_ind, f in enumerate(
        tqdm(highlights_files, unit="highlight", desc="importing highlights")
    ):
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
            raise RuntimeError(
                f"Could not find omnivore bookmark for highlight file: {name}"
            )
        url = omnivore["url"]

        # check if the highlight is from a pdf or an html
        assert name in content_files, name
        if content_files[name] == ".pdf":
            is_pdf = True
            if skip_pdf:
                continue
            else:
                raise NotImplementedError("PDF highlights are not yet supported")
        elif content_files[name] == ".html":
            is_pdf = False
        else:
            print("Is neither a webpage nor a pdf?!")
            raise RuntimeError(
                f"Unexpected file extension '{content_files[name]}' for file '{name}'. Expected '.pdf' or '.html'"
            )

        found_bm = False
        best_bookmark = None
        best_score = 0.0
        threshold = 0.95

        for bookmark in all_bm:
            found_url = None
            content = bookmark.content

            if is_pdf:
                raise NotImplementedError("PDF highlights are not yet supported")

            if hasattr(content, "url"):
                found_url = content.url
            elif hasattr(content, "sourceUrl"):
                found_url = content.sourceUrl
            else:
                raise RuntimeError(
                    f"Bookmark content has no 'url' or 'sourceUrl' attribute. Available attributes: {[attr for attr in dir(content) if not attr.startswith('_')]}"
                )

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

            # fuzzy matching, as a last resort - track the best match
            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(content, "title")
                and content.title
            ):
                r = ratio(omnivore["title"].lower(), content.title.lower())
                if r > best_score:
                    best_score = r
                    best_bookmark = bookmark

            if (
                "title" in omnivore
                and omnivore["title"]
                and hasattr(bookmark, "title")
                and bookmark.title
            ):
                r = ratio(omnivore["title"].lower(), bookmark.title.lower())
                if r > best_score:
                    best_score = r
                    best_bookmark = bookmark

        # Use the best fuzzy match if it meets the threshold
        if not found_bm and best_score >= threshold:
            found_bm = True
            bookmark = best_bookmark

        if not found_bm:
            print("Did not find the bookmark")
            raise RuntimeError(f"Could not find bookmark for highlight file: {name}")

        kara_content = bookmark.content.htmlContent

        if not kara_content:
            print(
                f"Skipping bookmark '{bookmark.title or name}' (ID: {bookmark.id}) - no HTML content available"
            )
            continue

        as_md = html2text(kara_content, bodywidth=9999999)

        as_text = BeautifulSoup(kara_content).get_text()

        for highlight in highlights:

            if highlight.startswith("> "):
                highlight = highlight[1:]
                highlight.strip()

            # fix URLs of omnivore to point to the original source
            highlight = re.sub(
                r"https://proxy-prod.omnivore-image-cache.app/.*https://",
                "https://",
                highlight,
            )

            high_as_text = BeautifulSoup(markdown.markdown(highlight)).get_text()

            link_pattern = r"\[.*?\]\((.*?)\)"
            link_replaced = re.sub(link_pattern, r" (Link to \1)", highlight)
            high_link_replaced_as_text = BeautifulSoup(
                markdown.markdown(link_replaced)
            ).get_text()

            if not high_link_replaced_as_text:
                assert (
                    high_link_replaced_as_text
                ), f"Empty highlight text after processing. Original highlight: {highlight[:200]}{'...' if len(highlight) > 200 else ''}, Link replaced: {link_replaced[:200]}{'...' if len(link_replaced) > 200 else ''}"

            start, end = find_highlight_position(
                high_as_text, highlight, as_text, as_md, kara_content
            )

            if not dry:
                resp = karakeep.create_a_new_highlight(
                    highlight_data={
                        "bookmarkId": bookmark.id,
                        "text": high_link_replaced_as_text,
                        "color": "yellow",
                        "note": f"By omnivore_highlights_importer.py version {VERSION}",
                        "startOffset": start,
                        "endOffset": end,
                    }
                )
                assert resp, highlight

            del high_as_text


if __name__ == "__main__":
    fire.Fire(main)
