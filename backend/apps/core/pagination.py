"""
Project-wide pagination (ARCHITECTURE.md §6).

DRF's stock PageNumberPagination ignores ?page_size= from the client; this
subclass enables it with a hard cap so a caller can ask for more rows per
page but can never request "?page_size=1000000" and stall the database.

Response shape (DRF default, no custom envelope):
    {"count": 57, "next": "...?page=3", "previous": "...?page=1", "results": [...]}
"""

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    page_size = 20  # rows per page when the client doesn't ask
    page_size_query_param = "page_size"  # client may override: ?page_size=50
    max_page_size = 100  # ...but never beyond this
