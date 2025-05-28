"""Adds time-to-read tags to bookmarks based on content length."""

import sys
import pickle
import fire
from pathlib import Path
from tqdm import tqdm
from bs4 import BeautifulSoup
from loguru import logger
from karakeep_python_api import KarakeepAPI


VERSION: str = "1.1.0"


class AddTimeToRead:
    """Class to add time-to-read tags to bookmarks based on content length."""

    # Define the time-to-read tags
    TIME_TAGS = ["0-5m", "5-10m", "10-15m", "15-30m", "30m+"]

    def __init__(self):
        """Initialize the AddTimeToRead class."""
        self.karakeep = None

    def setup_logging(self, verbose: bool = False):
        """Setup loguru logging with file output and console output based on verbosity."""
        # Remove default logger
        logger.remove()

        # Add file logger with debug level
        logger.add("add_time_to_read.log", level="DEBUG", rotation="10 MB")

        # Add console logger based on verbosity
        if verbose:
            logger.add(sys.stderr, level="DEBUG")
        else:
            logger.add(sys.stderr, level="INFO")

    def extract_content_text(self, bookmark) -> str:
        """
        Extract text content from bookmark based on its type.

        Args:
            bookmark: Bookmark object with content

        Returns:
            str: Text content to analyze
        """
        if bookmark.content.type == "link":
            # For link bookmarks, content is in bookmark.content.content
            return bookmark.content.htmlContent
        elif bookmark.content.type == "text":
            # For text bookmarks, content is in bookmark.content.text
            return bookmark.content.text
        else:
            logger.debug(f"Unsupported content type: {bookmark.content.type}")
            return ""

    def estimate_reading_time(self, bookmark, wpm: int) -> str:
        """
        Estimate reading time for given bookmark and return appropriate tag.

        Args:
            bookmark: Bookmark object to analyze
            wpm: Words per minute reading speed

        Returns:
            str: Time tag (0-5m, 5-10m, 10-15m, 15-30m, 30m+)
        """
        # Extract text content based on bookmark type
        content = self.extract_content_text(bookmark)

        if not content:
            logger.debug("Empty content, returning 0-5m tag")
            return "0-5m"

        # Parse HTML and extract text
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text()

        # Count words (split by whitespace)
        word_count = len(text.split())
        logger.debug(f"Word count: {word_count}")

        # Calculate reading time in minutes
        reading_time_minutes = word_count / wpm
        logger.debug(f"Estimated reading time: {reading_time_minutes:.2f} minutes")

        # Determine appropriate tag
        if reading_time_minutes <= 5:
            return "0-5m"
        elif reading_time_minutes <= 10:
            return "5-10m"
        elif reading_time_minutes <= 15:
            return "10-15m"
        elif reading_time_minutes <= 30:
            return "15-30m"
        else:
            return "30m+"

    def get_current_time_tags(self, bookmark) -> list:
        """Get list of current time-to-read tags on bookmark."""
        if not bookmark.tags:
            return []

        current_time_tags = []
        for tag in bookmark.tags:
            if tag.name in self.TIME_TAGS:
                current_time_tags.append(tag.name)

        return current_time_tags

    def should_skip_bookmark(self, bookmark, reset_all: bool) -> bool:
        """
        Determine if bookmark should be skipped based on reset_all setting.

        Logic:
        - If reset_all is True: never skip
        - If reset_all is False:
          - When using search mode, we've already filtered to untagged bookmarks, so never skip
          - This method is kept for consistency but simplified logic when not reset_all
        """
        if reset_all:
            return False

        # When reset_all is False, we've already used search to find untagged bookmarks
        # So we should process all bookmarks in the filtered set
        # However, we still check for multiple time tags that might need reset
        current_time_tags = self.get_current_time_tags(bookmark)

        # If exactly one time tag, this shouldn't happen in search mode but handle gracefully
        if len(current_time_tags) == 1:
            logger.debug(
                f"Unexpected: bookmark {bookmark.id} found in search but has time tag: {current_time_tags[0]}"
            )
            return True

        # Process bookmarks with multiple time tags or no time tags
        return False

    def needs_reset(self, bookmark) -> bool:
        """Check if bookmark has multiple time tags and needs reset."""
        current_time_tags = self.get_current_time_tags(bookmark)
        return len(current_time_tags) > 1

    def process_bookmark(self, bookmark, wpm: int):
        """Process a single bookmark to add appropriate time-to-read tag."""
        logger.debug(f"Processing bookmark {bookmark.id}: {bookmark.title}")

        # Only process link and text bookmarks
        if bookmark.content.type not in ["link", "text"]:
            logger.debug(
                f"Skipping bookmark {bookmark.id} - type {bookmark.content.type} not supported"
            )
            return

        # Estimate reading time
        target_tag = self.estimate_reading_time(bookmark, wpm)
        logger.debug(f"Target tag for bookmark {bookmark.id}: {target_tag}")

        # Get current time tags
        current_time_tags = self.get_current_time_tags(bookmark)
        logger.debug(
            f"Current time tags for bookmark {bookmark.id}: {current_time_tags}"
        )

        # If bookmark already has the correct tag and no others, skip
        if current_time_tags == [target_tag]:
            logger.debug(f"Bookmark {bookmark.id} already has correct tag")
            return

        # Remove all existing time tags if any
        if current_time_tags:
            logger.info(
                f"Removing existing time tags {current_time_tags} from bookmark {bookmark.id}"
            )
            try:
                self.karakeep.detach_tags_from_a_bookmark(
                    bookmark_id=bookmark.id, tag_names=current_time_tags
                )
            except Exception as e:
                logger.error(f"Failed to remove tags from bookmark {bookmark.id}: {e}")
                return

        # Add the target tag
        logger.info(
            f"Adding tag '{target_tag}' to bookmark {bookmark.id}: {bookmark.title}"
        )
        try:
            self.karakeep.attach_tags_to_a_bookmark(
                bookmark_id=bookmark.id, tag_names=[target_tag]
            )
        except Exception as e:
            logger.error(f"Failed to add tag to bookmark {bookmark.id}: {e}")

    def run(
        self,
        wpm: int = 200,
        reset_all: bool = False,
        verbose: bool = False,
        cache_file: str = "./bookmarks.temp",
    ):
        """
        Main method to process all bookmarks and add time-to-read tags.

        Args:
            wpm: Words per minute reading speed (default: 200)
            reset_all: If True, process all bookmarks. If False, skip bookmarks that already have a single time tag.
            verbose: If True, show debug level logs in console
            cache_file: Path to cache file for bookmarks (default: ./bookmarks.temp)
        """
        # Setup logging
        self.setup_logging(verbose)

        logger.info(f"Starting AddTimeToRead with wpm={wpm}, reset_all={reset_all}")

        # Connect to Karakeep
        try:
            self.karakeep = KarakeepAPI()
            logger.info("Connected to Karakeep API")
        except Exception as e:
            logger.error(f"Failed to connect to Karakeep API: {e}")
            return

        # Determine cache file name based on reset_all mode
        if reset_all:
            cache_file_final = cache_file
        else:
            # Use different cache for untagged bookmarks search
            cache_parts = Path(cache_file).parts
            cache_file_final = str(
                Path(*cache_parts[:-1]) / f"untagged_{cache_parts[-1]}"
            )

        # Fetch bookmarks with content, using cache to speed up testing
        # As the loading can be pretty long, we store it to a local file
        if reset_all:
            if Path(cache_file_final).exists():
                logger.info(f"Loading bookmarks from cache file: {cache_file_final}")
                with Path(cache_file_final).open("rb") as f:
                    bookmarks = pickle.load(f)
                logger.info(f"Loaded {len(bookmarks)} bookmarks from cache")
            else:
                logger.info("Cache file not found, fetching bookmarks from API...")

                # Fetch all bookmarks when reset_all is True
                try:
                    n = self.karakeep.get_current_user_stats()["numBookmarks"]
                    logger.info(f"Total bookmarks to fetch: {n}")
                except Exception as e:
                    logger.error(f"Failed to get bookmark count: {e}")
                    return

                logger.info("Fetching all bookmarks with content...")
                pbar = tqdm(total=n, desc="Fetching bookmarks")
                bookmarks = []
                batch_size = 100  # Maximum allowed batch size to avoid crashing the karakeep instance

                try:
                    page = self.karakeep.get_all_bookmarks(
                        include_content=True,
                        limit=batch_size,
                    )
                    bookmarks.extend(page.bookmarks)
                    pbar.update(len(page.bookmarks))

                    while page.nextCursor:
                        page = self.karakeep.get_all_bookmarks(
                            include_content=True,
                            limit=batch_size,
                            cursor=page.nextCursor,
                        )
                        bookmarks.extend(page.bookmarks)
                        pbar.update(len(page.bookmarks))

                    assert (
                        len(bookmarks) == n
                    ), f"Only retrieved {len(bookmarks)} bookmarks instead of {n}"
                    pbar.close()

                except Exception as e:
                    pbar.close()
                    logger.error(f"Error fetching bookmarks: {e}")
                    return

            # Save bookmarks to cache file
            logger.info(
                f"Saving {len(bookmarks)} bookmarks to cache file: {cache_file_final}"
            )
            with Path(cache_file_final).open("wb") as f:
                pickle.dump(bookmarks, f)
        else:
            # Use search to find bookmarks without time tags when reset_all is False
            search_query = "-#0-5m -#5-10m -#10-15m -#15-30m -#30m+"
            logger.info(
                f"Searching for bookmarks without time tags using query: {search_query}"
            )

            bookmarks = []
            batch_size = 100

            try:
                page = self.karakeep.search_bookmarks(
                    q=search_query,
                    include_content=True,
                    limit=batch_size,
                )
                bookmarks.extend(page.bookmarks)
                logger.info(f"Found {len(page.bookmarks)} bookmarks in first page")

                while page.nextCursor:
                    page = self.karakeep.search_bookmarks(
                        q=search_query,
                        include_content=True,
                        limit=batch_size,
                        cursor=page.nextCursor,
                    )
                    bookmarks.extend(page.bookmarks)
                    logger.info(f"Found {len(page.bookmarks)} additional bookmarks")

                logger.info(f"Total untagged bookmarks found: {len(bookmarks)}")

            except Exception as e:
                logger.error(f"Error searching for untagged bookmarks: {e}")
                return

        logger.info(f"Total bookmarks fetched: {len(bookmarks)}")

        # Process bookmarks
        processed = 0
        skipped_by_policy = 0
        skipped_by_type = 0
        errors = 0

        for bookmark in tqdm(bookmarks, desc="Processing bookmarks"):
            try:
                # Check bookmark type first
                if bookmark.content.type not in ["link", "text"]:
                    skipped_by_type += 1
                    continue

                # Check if we should skip this bookmark based on reset policy
                if self.should_skip_bookmark(bookmark, reset_all):
                    skipped_by_policy += 1
                    continue

                # Check if bookmark needs reset (has multiple time tags)
                if self.needs_reset(bookmark):
                    logger.info(
                        f"Bookmark {bookmark.id} has multiple time tags, will be reset"
                    )

                # Process the bookmark
                self.process_bookmark(bookmark, wpm)
                processed += 1

            except Exception as e:
                logger.error(f"Error processing bookmark {bookmark.id}: {e}")
                errors += 1

        logger.info(
            f"Processing complete. Processed: {processed}, Skipped (policy): {skipped_by_policy}, Skipped (type): {skipped_by_type}, Errors: {errors}"
        )

        # Clean up cache file after successful completion
        if Path(cache_file_final).exists():
            try:
                Path(cache_file_final).unlink()
                logger.info(f"Cleaned up cache file: {cache_file_final}")
            except Exception as e:
                logger.warning(f"Failed to delete cache file {cache_file_final}: {e}")


def main(
    wpm: int = 200,
    reset_all: bool = False,
    verbose: bool = False,
    cache_file: str = "./bookmarks.temp",
):
    """
    Main entry point for the script.

    Args:
        wpm: Words per minute reading speed (default: 200)
        reset_all: If True, process all bookmarks. If False, skip bookmarks that already have a single time tag.
        verbose: If True, show debug level logs in console
        cache_file: Path to cache file for bookmarks (default: ./bookmarks.temp)
    """
    add_time_to_read = AddTimeToRead()
    add_time_to_read.run(
        wpm=wpm, reset_all=reset_all, verbose=verbose, cache_file=cache_file
    )


if __name__ == "__main__":
    fire.Fire(main)
