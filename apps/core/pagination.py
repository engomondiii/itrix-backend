"""
Pagination.

The dashboard's lead list expects a payload shaped like::

    { "results": [...], "count": N, "page": P, "pageSize": S }

(see ``itrix-dashboard/src/types/api.ts`` → ``Paginated<T>``). ``page``/``pageSize``
query params drive it. ``StandardResultsPagination`` produces exactly that shape so
the dashboard's mock contract and the live backend are interchangeable.
"""

from __future__ import annotations

from collections import OrderedDict

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "pageSize"
    page_query_param = "page"
    max_page_size = 200

    def get_paginated_response(self, data) -> Response:
        return Response(
            OrderedDict(
                [
                    ("results", data),
                    ("count", self.page.paginator.count),
                    ("page", self.page.number),
                    ("pageSize", self.get_page_size(self.request)),
                    ("totalPages", self.page.paginator.num_pages),
                ]
            )
        )

    def get_paginated_response_schema(self, schema):  # pragma: no cover
        return {
            "type": "object",
            "properties": {
                "results": schema,
                "count": {"type": "integer"},
                "page": {"type": "integer"},
                "pageSize": {"type": "integer"},
                "totalPages": {"type": "integer"},
            },
        }


class SmallResultsPagination(StandardResultsPagination):
    page_size = 10
    max_page_size = 50
