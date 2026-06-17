"""
Report sections.

Turns the analytics blocks into plain-English narrative sections for a monthly report. Each
section is ``{id, title, body}`` (the dashboard's ReportSection). Language is factual and
qualitative, consistent with the brand's claims discipline.
"""

from __future__ import annotations


def _pct(x: float) -> str:
    return f"{round(x * 100)}%"


def build_sections(analytics: dict, *, month: str) -> list[dict]:
    overview = analytics.get("overview", {})
    funnel = analytics.get("funnel", [])
    rt = analytics.get("response_time", {})
    bottlenecks = analytics.get("bottlenecks", [])
    industries = analytics.get("industries", [])
    routes = analytics.get("route_distribution", {})

    sections: list[dict] = []

    # 1. Summary
    sections.append(
        {
            "id": "summary",
            "title": "Summary",
            "body": (
                f"In the period ending {month}, {overview.get('newLeads', 0)} new leads entered "
                f"the pipeline, including {overview.get('tier1Count', 0)} Tier 1 (strategic) and "
                f"{overview.get('tier2Count', 0)} Tier 2 (qualified) leads. There are currently "
                f"{overview.get('overdueFollowUps', 0)} overdue follow-ups."
            ),
        }
    )

    # 2. Funnel
    if funnel:
        parts = ", ".join(f"{s['stage']}: {s['count']}" for s in funnel)
        sections.append(
            {
                "id": "funnel",
                "title": "Conversion funnel",
                "body": f"Lead progression through the pipeline — {parts}.",
            }
        )

    # 3. Response time / SLA
    sections.append(
        {
            "id": "response_time",
            "title": "Response time & SLA",
            "body": (
                f"Average first-response time was {rt.get('tier1AvgHours', 0)}h for Tier 1 and "
                f"{rt.get('tier2AvgHours', 0)}h for Tier 2. SLA compliance was "
                f"{_pct(rt.get('complianceRate', 0))}, with {rt.get('tier1Breaches', 0)} Tier 1 "
                f"and {rt.get('tier2Breaches', 0)} Tier 2 breaches."
            ),
        }
    )

    # 4. Routes
    if routes:
        parts = ", ".join(f"{k}: {v}" for k, v in routes.items())
        sections.append(
            {
                "id": "routes",
                "title": "Product route distribution",
                "body": f"Leads routed by product interest — {parts}.",
            }
        )

    # 5. Bottlenecks
    if bottlenecks:
        parts = ", ".join(f"{b['phrase']} ({b['count']})" for b in bottlenecks[:6])
        sections.append(
            {
                "id": "bottlenecks",
                "title": "Common bottleneck patterns",
                "body": f"The most frequently cited computation bottlenecks were: {parts}.",
            }
        )

    # 6. Industries
    if industries:
        parts = ", ".join(f"{i['industry']} ({i['count']})" for i in industries[:6])
        sections.append(
            {
                "id": "industries",
                "title": "Industry breakdown",
                "body": f"Leads by industry — {parts}.",
            }
        )

    return sections
