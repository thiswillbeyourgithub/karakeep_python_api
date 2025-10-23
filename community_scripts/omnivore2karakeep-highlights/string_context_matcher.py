from typing import List
from math import inf
from dataclasses import dataclass

from joblib import Parallel, delayed, Memory
from rapidfuzz.distance.Levenshtein import normalized_distance as lev_dist
from rapidfuzz.fuzz import ratio as lev_ratio

# Initialize joblib Memory for caching
# Using a distinct cache name for this module
mem = Memory(".cache_string_matcher", verbose=False)


@dataclass
class MatchResult:
    """
    Holds the results of a highlight matching operation.

    Attributes:
    - matches: List of best matching substrings of corpus.
    - ratio: Levenshtein ratio of the closest match.
    - distance: Levenshtein distance of the closest match.
    - quick_match_used: True if the quick matching algorithm was used, False otherwise.
    """

    matches: List[str]
    ratio: float
    distance: (
        float  # Levenshtein distance is usually int, but normalized_distance is float
    )
    quick_match_used: bool


@mem.cache(ignore=["n_jobs"])
def match_highlight_to_corpus(
    query: str,
    corpus: str,
    case_sensitive: bool = True,
    step_factor: int = 500,
    n_jobs: int = -1,
) -> MatchResult:
    """
    Source: https://stackoverflow.com/questions/36013295/find-best-substring-match
    Returns the substring of the corpus with the least Levenshtein distance from the query
    (May not always return optimal answer).

    Arguments
    - query: str
    - corpus: str
    - case_sensitive: bool
    - step_factor: int
        Only used in the long way.
        Influences the resolution of the thorough search once the general region is found.
        The increment in ngrams lengths used for the thorough search is calculated as len(query)//step_factor.
        Increasing this increases the number of ngram lengths used in the thorough search and increases the chances
        of getting the optimal solution at the cost of runtime and memory.
    - n_jobs: int
        number of jobs to use for multithreading. 1 to disable

    Returns
    MatchResult object containing:
        - matches: List of best matching substrings of corpus,
        - ratio: Levenshtein ratio of closest match,
        - distance: Levenshtein distance of closest match,
        - quick_match_used: True if used the quick way False if using the long way,
    """

    # quick way
    lq = len(query)
    lc = len(corpus)

    # Prepare query and corpus for caseless comparison if needed for word matching
    # but original query/corpus are used for levenshtein to respect case_sensitive flag later if it were used.
    # Note: The current 'quick way' does not explicitly use the case_sensitive flag for its Levenshtein comparisons.
    # It uses casefolded strings for identifying regions.
    lquery_caseless = query.casefold()
    lcorp_caseless = corpus.casefold()

    # 1. find most probably region that contains the appropriate words
    qwords = [w.strip() for w in set(lquery_caseless.split(" ")) if len(w.strip()) > 3]
    indexes = []
    for w in qwords:
        m = []
        prev = 0
        # Search for word occurrences in the case-folded corpus
        while True:
            try:
                found_idx = lcorp_caseless.index(w, prev)
                m.append(found_idx)
                prev = found_idx + 1
                if len(m) >= 20:  # Limit number of matches per word
                    break
            except ValueError:  # Substring not found
                break
        if len(m) > 20:  # if limit was reached (and thus potentially many more matches)
            continue  # this word might be too common, skip it
        if m:
            indexes.append(m)

    if indexes:
        mins = [min(ind_list) for ind_list in indexes]
        maxs = [max(ind_list) for ind_list in indexes]
        # Calculate mean start and end points, expand by 1.2 * query length
        mean_min = max(0, int(sum(mins) / len(mins)) - int(lq * 1.2))
        mean_max = min(lc, int(sum(maxs) / len(maxs)) + int(lq * 1.2))

        mini_corp = corpus[mean_min : mean_max + 1]

        # 2. in the region, check the lev ratio in a sliding window
        # to determine best sub region
        # Create batches of query length from the mini_corp
        batches = [
            mini_corp[i * lq : (i + 1) * lq] for i in range(0, len(mini_corp) // lq + 1)
        ]
        batches = [b for b in batches if b.strip()]  # Filter out empty batches

        if not batches:  # No suitable batches found
            pass  # Will proceed to the "long way" or return based on later logic
        else:
            ratios = Parallel(
                backend="threading",
                n_jobs=n_jobs,
            )(delayed(lev_ratio)(query, b) for b in batches)  # Use lev_ratio
            max_rat = max(ratios) if ratios else -1.0
            max_rat_idx = [i for i, r in enumerate(ratios) if r == max_rat]

            # 3. in the best sub region, find the best substring with a 1
            # character sliding window using both ratio and distance
            best_ratio = -inf
            best_dist = inf
            best_matches = []

            def get_rat_dist(s1, s2):
                # Corrected to use imported lev_ratio and lev_dist
                return [lev_ratio(s1, s2), lev_dist(s1, s2)]

            for current_region_idx_in_batches in max_rat_idx:
                # Define area based on batches around the current max_rat_idx
                # Original: "".join(batches[current_region_idx_in_batches-1:current_region_idx_in_batches+1])
                # This needs careful handling of start/end of batches list
                start_slice = max(0, current_region_idx_in_batches - 1)
                end_slice = (
                    current_region_idx_in_batches + 1
                )  # Slicing is exclusive at end

                # The string to find index of, from the original batches
                string_markers_for_iidx = "".join(batches[start_slice:end_slice])

                try:
                    # Find this concatenated marker string within mini_corp to get a starting point
                    iidx = mini_corp.index(string_markers_for_iidx)
                except ValueError:
                    # If the joined string isn't found (e.g., if batches were empty or logic error)
                    # try to use the start of the current batch element as a fallback index.
                    if batches and current_region_idx_in_batches < len(batches):
                        try:
                            iidx = mini_corp.index(
                                batches[current_region_idx_in_batches]
                            )
                        except ValueError:
                            continue  # Skip this max_rat_idx if problematic
                    else:
                        continue  # Skip this max_rat_idx if problematic

                area = mini_corp[
                    iidx : iidx + 3 * lq
                ]  # Define search area in mini_corp
                if not area.strip():
                    continue

                # Generate sub-batches (batches2) from this 'area'
                # Original: [area[i:lq+i] for i in range(0, len(area) + 1)]
                # This creates n-grams of length lq, then shorter suffixes.
                batches2 = [area[i : i + lq] for i in range(0, len(area) - lq + 1)]
                # Add shorter suffixes as in original intent (approximation):
                for k in range(1, lq):
                    if len(area) - lq + k < len(area):
                        batches2.append(area[len(area) - lq + k :])
                batches2 = [b for b in batches2 if b]  # Ensure no empty strings

                if not batches2:
                    continue

                ratdist2 = Parallel(
                    backend="threading",
                    n_jobs=n_jobs,
                )(delayed(get_rat_dist)(query, b) for b in batches2)

                ratios2 = [it[0] for it in ratdist2]
                distances2 = [it[1] for it in ratdist2]

                current_batch_max_r = max(ratios2) if ratios2 else -inf
                current_batch_min_d = min(distances2) if distances2 else inf

                # Original logic for updating global best_matches
                if (
                    current_batch_max_r >= best_ratio
                    and current_batch_min_d <= best_dist
                ):
                    # Find all strings in batches2 that yield current_batch_max_r
                    indices_for_current_max_r = [
                        i
                        for i, r_val in enumerate(ratios2)
                        if r_val == current_batch_max_r
                    ]

                    if (
                        not indices_for_current_max_r
                    ):  # Should not happen if current_batch_max_r is from ratios2
                        continue

                    # Pick the first one as per original's implied logic (using index())
                    candidate_string_from_batch = batches2[indices_for_current_max_r[0]]

                    if (
                        current_batch_max_r == best_ratio
                        and current_batch_min_d == best_dist
                    ):
                        best_matches.append(candidate_string_from_batch)
                    else:  # New global bests found from this sub-batch's characteristics
                        best_ratio = current_batch_max_r
                        best_dist = current_batch_min_d
                        best_matches = [candidate_string_from_batch]

            if best_matches:
                best_matches = list(set(best_matches))  # Deduplicate
                return MatchResult(
                    matches=best_matches,
                    ratio=best_ratio,
                    distance=best_dist,
                    quick_match_used=True,
                )

    # Fallback or "long way" if quick way did not yield results or was skipped
    query_to_compare = query if case_sensitive else query.casefold()
    corpus_to_compare = corpus if case_sensitive else corpus.casefold()

    corpus_len = len(corpus_to_compare)
    query_len = len(query_to_compare)
    if query_len == 0:
        return MatchResult(
            matches=[], ratio=0.0, distance=1.0, quick_match_used=False
        )  # Or handle as error
    if corpus_len == 0:
        return MatchResult(matches=[], ratio=0.0, distance=1.0, quick_match_used=False)

    query_len_by_2 = max(query_len // 2, 1)
    query_len_by_step_factor = max(query_len // step_factor, 1)

    min_dist_val = inf  # Renamed from min_dist to avoid clash with the variable from quick path if it ran partially

    # Initial search of corpus: ngrams of same length as query, step half query length
    corpus_ngrams_initial = [
        corpus_to_compare[i : i + query_len]
        for i in range(0, corpus_len - query_len + 1, query_len_by_2)
    ]
    if not corpus_ngrams_initial:  # e.g. corpus shorter than query
        # Try one comparison with the full corpus if it's shorter than query_len
        if corpus_len < query_len:
            corpus_ngrams_initial = [corpus_to_compare]
        else:  # No ngrams to check, means cannot find match.
            # Check what ratio/distance to return for "no match"
            # An empty list of matches, ratio 0, distance 1 (max normalized distance)
            return MatchResult(
                matches=[], ratio=0.0, distance=1.0, quick_match_used=False
            )

    dists_initial = Parallel(
        backend="threading",
        n_jobs=n_jobs,
    )(delayed(lev_dist)(ngram, query_to_compare) for ngram in corpus_ngrams_initial)

    closest_match_idx_initial = 0
    if dists_initial:
        min_dist_val = min(dists_initial)
        closest_match_idx_initial = dists_initial.index(min_dist_val)
    else:  # No initial distances, implies no ngrams, return no match
        return MatchResult(matches=[], ratio=0.0, distance=1.0, quick_match_used=False)

    # Determine narrowed search region based on initial best match
    closest_match_corpus_start_idx = closest_match_idx_initial * query_len_by_2

    # Define search window around this initial best match point
    # Original boundaries:
    # left = max(closest_match_idx - query_len_by_2 - 1, 0)
    # right = min((closest_match_idx+query_len-1) + query_len_by_2 + 2, corpus_len)
    # Using corpus indices:
    left_boundary = max(0, closest_match_corpus_start_idx - query_len_by_2 - 1)
    # The end of the initial best ngram is closest_match_corpus_start_idx + query_len
    right_boundary = min(
        corpus_len,
        (closest_match_corpus_start_idx + query_len - 1) + query_len_by_2 + 2,
    )

    narrowed_corpus_to_compare = corpus_to_compare[left_boundary:right_boundary]
    # Important: We need to map findings in narrowed_corpus_to_compare back to original `corpus` strings
    narrowed_corpus_original_case = corpus[left_boundary:right_boundary]

    narrowed_corpus_len = len(narrowed_corpus_to_compare)
    if narrowed_corpus_len == 0:
        return MatchResult(matches=[], ratio=0.0, distance=1.0, quick_match_used=False)

    # Generate ngram lengths for thorough search in the narrowed region
    # From narrowed_corpus_len down to query_len_by_2, stepping by -query_len_by_step_factor
    ngram_lens_thorough = [
        l
        for l in range(
            narrowed_corpus_len, query_len_by_2 - 1, -query_len_by_step_factor
        )
        if l > 0
    ]
    if (
        not ngram_lens_thorough
    ):  # If narrowed_corpus_len is too small or other edge cases
        ngram_lens_thorough.append(
            min(query_len, narrowed_corpus_len)
        )  # Ensure at least one sensible length
        ngram_lens_thorough = [l for l in ngram_lens_thorough if l > 0]

    # Construct sets of ngrams from narrowed_corpus for each length
    narrowed_corpus_ngrams_thorough_sets = []
    narrowed_corpus_ngrams_original_case_sets = []

    for ngram_len in ngram_lens_thorough:
        if ngram_len > narrowed_corpus_len:
            continue  # Should not happen if ngram_lens_thorough is generated correctly
        current_set_compare = [
            narrowed_corpus_to_compare[i : i + ngram_len]
            for i in range(0, narrowed_corpus_len - ngram_len + 1)
        ]
        current_set_original = [
            narrowed_corpus_original_case[i : i + ngram_len]
            for i in range(0, narrowed_corpus_len - ngram_len + 1)
        ]
        if current_set_compare:
            narrowed_corpus_ngrams_thorough_sets.append(current_set_compare)
            narrowed_corpus_ngrams_original_case_sets.append(current_set_original)

    if not narrowed_corpus_ngrams_thorough_sets:
        # This can happen if narrowed_corpus is shorter than all generated ngram_lens
        # e.g. query_len_by_2 is too large relative to narrowed_corpus_len
        # As a fallback, compare query against the whole narrowed_corpus_original_case
        dist_val = lev_dist(narrowed_corpus_to_compare, query_to_compare)
        ratio_val = lev_ratio(narrowed_corpus_to_compare, query_to_compare)
        if dist_val <= min_dist_val:  # Using min_dist_val from initial pass
            return MatchResult(
                matches=[narrowed_corpus_original_case],
                ratio=ratio_val,
                distance=dist_val,
                quick_match_used=False,
            )
        else:  # Initial pass was better or no match found
            # This part needs to re-evaluate what to return if narrowed search fails.
            # Fallback to returning based on min_dist_val if nothing better is found here.
            # For now, let's assume if we reach here with no ngrams, original min_dist_val holds the best.
            # This path implies the more thorough search didn't find anything or couldn't run.
            # Find the string associated with min_dist_val from initial pass:
            best_ngram_from_initial_pass_idx = dists_initial.index(min_dist_val)
            best_ngram_str_initial_pass_original_case = corpus[
                best_ngram_from_initial_pass_idx
                * query_len_by_2 : best_ngram_from_initial_pass_idx * query_len_by_2
                + query_len
            ]
            ratio_for_initial_best = lev_ratio(
                (
                    best_ngram_str_initial_pass_original_case.casefold()
                    if not case_sensitive
                    else best_ngram_str_initial_pass_original_case
                ),
                query_to_compare,
            )
            return MatchResult(
                matches=[best_ngram_str_initial_pass_original_case],
                ratio=ratio_for_initial_best,
                distance=min_dist_val,
                quick_match_used=False,
            )

    # Calculate distances for all ngrams in the thorough search sets
    dist_list_thorough = []
    for ngram_set in narrowed_corpus_ngrams_thorough_sets:
        dist_list_thorough.append(
            Parallel(backend="threading", n_jobs=n_jobs)(
                delayed(lev_dist)(ngram, query_to_compare) for ngram in ngram_set
            )
        )

    final_best_matches = []
    # min_dist_val still holds the minimum distance found so far (from initial pass)

    for i_set, ngram_set_original_case in enumerate(
        narrowed_corpus_ngrams_original_case_sets
    ):
        current_dists_for_set = dist_list_thorough[i_set]
        for i_ngram, ngram_original_case in enumerate(ngram_set_original_case):
            ngram_dist = current_dists_for_set[i_ngram]
            if ngram_dist < min_dist_val:
                min_dist_val = ngram_dist
                final_best_matches = [ngram_original_case]
            elif ngram_dist == min_dist_val:
                final_best_matches.append(ngram_original_case)

    # If initial pass found a better or equal min_dist_val and thorough search didn't improve OR final_best_matches empty
    if not final_best_matches:
        # Fallback to best from initial pass if thorough search yielded nothing
        # This case should ideally be covered by min_dist_val initialization and updates
        # For safety, ensure if final_best_matches is empty, we use the best known from initial scan.
        idx = dists_initial.index(min_dist_val)
        # Original string from corpus that corresponds to this match
        original_string_match = corpus[
            idx * query_len_by_2 : idx * query_len_by_2 + query_len
        ]
        final_best_matches = [original_string_match]

    final_best_matches = list(set(final_best_matches))  # Deduplicate
    if not final_best_matches:  # Should not be empty if corpus & query were not empty
        return MatchResult(matches=[], ratio=0.0, distance=1.0, quick_match_used=False)

    # Calculate ratio for the first best match found (or an aggregate if multiple have same min_dist_val)
    # Ensure query_to_compare is used for ratio calculation consistency
    # best_ratio_val = lev_ratio( # Original calculation commented for review
    # (final_best_matches[0].casefold() if not case_sensitive else final_best_matches[0]),
    # query_to_compare
    # )
    # Re-calculate max ratio among all best_matches to be robust
    all_ratios = [
        lev_ratio((bm.casefold() if not case_sensitive else bm), query_to_compare)
        for bm in final_best_matches
    ]
    best_ratio_val = max(all_ratios) if all_ratios else 0.0
    # The min_dist_val should already be correct for these final_best_matches

    return MatchResult(
        matches=final_best_matches,
        ratio=best_ratio_val,
        distance=min_dist_val,
        quick_match_used=False,
    )  # False: used long way
