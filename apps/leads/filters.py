"""
Lead filtering.

Backs the dashboard's leads-table query params (``itrix-dashboard`` lead list):
``tier``, ``route``, ``status``, ``owner``, ``search``, plus score-range and sort. The
``route`` filter accepts both the canonical code (``alpha_compute``) and the dashboard's
display string ("ALPHA Compute"); ``search`` spans company / name / email / industry /
primary pain.
"""

from __future__ import annotations

import uuid

import django_filters as df
from django.db.models import Q

from apps.leads.models import Lead

_ROUTE_DISPLAY_TO_CODE = {
    "alpha compute": "alpha_compute",
    "alpha core": "alpha_core",
    "both": "both",
    "general": "general",
}


class LeadFilter(df.FilterSet):
    tier = df.NumberFilter(field_name="tier")
    status = df.CharFilter(field_name="status", lookup_expr="iexact")
    owner = df.CharFilter(method="filter_owner")
    route = df.CharFilter(method="filter_route")
    score_min = df.NumberFilter(field_name="score", lookup_expr="gte")
    score_max = df.NumberFilter(field_name="score", lookup_expr="lte")
    search = df.CharFilter(method="filter_search")

    class Meta:
        model = Lead
        fields = ["tier", "status", "owner", "route", "score_min", "score_max"]

    def filter_route(self, queryset, name, value):
        if not value:
            return queryset
        code = _ROUTE_DISPLAY_TO_CODE.get(value.strip().lower(), value.strip().lower())
        return queryset.filter(product_route=code)

    def filter_owner(self, queryset, name, value):
        if not value:
            return queryset
        # Accept owner display name / email, or a UUID id when it parses as one.
        condition = Q(owner__name__iexact=value) | Q(owner__email__iexact=value)
        try:
            uuid.UUID(str(value))
            condition |= Q(owner__id=value)
        except (ValueError, TypeError):
            pass
        return queryset.filter(condition)

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(company__icontains=value)
            | Q(visitor_name__icontains=value)
            | Q(email__icontains=value)
            | Q(industry__icontains=value)
            | Q(primary_pain__icontains=value)
        )
