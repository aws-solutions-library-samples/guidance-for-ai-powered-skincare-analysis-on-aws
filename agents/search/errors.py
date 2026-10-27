"""Search failures remain distinct from successful empty catalog results."""


class SearchUnavailable(RuntimeError):
    pass


class SearchDeadlineExceeded(SearchUnavailable):
    pass


class InvalidSearchResponse(SearchUnavailable):
    pass


class CatalogIntegrityError(RuntimeError):
    """A publication conflict that requires a reviewed repair or new generation."""
