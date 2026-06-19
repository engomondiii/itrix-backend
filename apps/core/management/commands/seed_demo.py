"""
``python manage.py seed_demo [--flush]``

Populates the database with realistic demo data for a live presentation so that an
operator can log into the itriX dashboard and see **every** screen populated:

* a login admin user (``demo@itrix.ai`` / ``demo12345``) + a small team
* leads spanning every pipeline stage, with activities, notes and a meeting
* NDAs / evaluations / PoCs for leads at the matching stage (built via the apps'
  own creator services so the data matches what the app would really produce)
* follow-up tasks (overdue / due today / upcoming / snoozed)
* notifications (varied kinds, some unread)
* one template per kind, a monthly report, and SLA thresholds

The command is **idempotent**. Re-running without ``--flush`` uses get_or_create /
the idempotent creator services, so it won't duplicate. ``--flush`` first deletes
the demo rows this command owns (scoped to the demo team users and the leads they
own — it never blindly truncates a table).
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.evaluations.models import Evaluation, EvaluationStatus
from apps.evaluations.services.evaluation_creator import create_evaluation_for_lead
from apps.follow_up.models import FollowUpStatus, FollowUpTask
from apps.leads.models import (
    CommercialPathCode,
    Lead,
    LeadActivity,
    LeadMeeting,
    LeadNote,
    LeadStatus,
    ProductRouteCode,
    SpecialRights,
)
from apps.nda.models import NDARecord, NDAStatus
from apps.nda.services.nda_creator import create_nda_for_lead
from apps.notifications.models import Notification
from apps.pocs.models import PoC, PoCStatus
from apps.pocs.services.poc_creator import create_poc_for_lead
from apps.reporting.models import MonthlyReport
from apps.settings.models import SlaThresholds
from apps.templates_library.models import Template, TemplateKind

User = get_user_model()

# Everything this command owns is namespaced under this email domain so --flush
# can scope its deletes and never touch real data.
DEMO_DOMAIN = "demo.itrix.ai"
ADMIN_EMAIL = "demo@itrix.ai"
ADMIN_PASSWORD = "demo12345"


def _h(n: int) -> dt.timedelta:
    return dt.timedelta(hours=n)


def _d(n: int) -> dt.timedelta:
    return dt.timedelta(days=n)


class Command(BaseCommand):
    help = "Populate the database with realistic demo data for a live presentation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete demo rows owned by this command before reseeding.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        self.now = timezone.now()
        if opts["flush"]:
            self._flush()

        admin = self._seed_admin()
        team = self._seed_team()
        owners = [admin] + team

        leads = self._seed_leads(owners)
        self._seed_lead_timeline(leads, admin)
        self._seed_stage_artifacts(leads)
        self._seed_follow_ups(leads, owners)
        self._seed_notifications(leads)
        self._seed_templates()
        self._seed_report()
        self._seed_sla()

        self._summary(admin)

    # ── flush ────────────────────────────────────────────────────────────────
    def _flush(self):
        self.stdout.write(self.style.WARNING("Flushing existing demo data..."))
        demo_users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}") | User.objects.filter(
            email=ADMIN_EMAIL
        )
        demo_leads = Lead.objects.filter(owner__in=demo_users)
        # Children cascade off Lead, but follow-ups / notifications also key off it.
        n_leads = demo_leads.count()
        demo_leads.delete()  # cascades: notes, meetings, activities, nda, evals, pocs, follow-ups, notifications
        n_users = demo_users.count()
        demo_users.delete()
        # Singletons / shared records this command also (re)creates.
        Template.objects.filter(name__startswith="[Demo]").delete()
        MonthlyReport.objects.filter(month=self._report_month()).delete()
        Notification.objects.filter(lead__isnull=True, title__startswith="[Demo]").delete()
        self.stdout.write(f"  removed {n_leads} demo leads and {n_users} demo users")

    # ── users ────────────────────────────────────────────────────────────────
    def _seed_admin(self) -> "User":
        admin, created = User.objects.get_or_create(
            email=ADMIN_EMAIL,
            defaults={
                "name": "Demo Operator",
                "role": User.Role.ADMIN,
                "team_role": User.TeamRole.ADMIN,
                "is_staff": True,
                "is_active": True,
                "is_superuser": True,
            },
        )
        # Always (re)set the known password / flags so login is guaranteed to work.
        admin.name = "Demo Operator"
        admin.role = User.Role.ADMIN
        admin.team_role = User.TeamRole.ADMIN
        admin.is_staff = True
        admin.is_active = True
        admin.is_superuser = True
        admin.set_password(ADMIN_PASSWORD)
        admin.save()
        self.stdout.write(self.style.SUCCESS(f"  {'created' if created else 'updated'} admin {ADMIN_EMAIL}"))
        return admin

    def _seed_team(self) -> list["User"]:
        members = [
            ("Maya Chen", "maya", User.Role.ASSESSMENT, User.TeamRole.ASSESSMENT_TEAM),
            ("Daniel Okoro", "daniel", User.Role.ASSESSMENT, User.TeamRole.TECHNICAL_REVIEW),
            ("Sofia Ricci", "sofia", User.Role.SPECIALIST, User.TeamRole.EXPERT_CONCIERGE),
            ("Jun-ho Park", "junho", User.Role.SPECIALIST, User.TeamRole.SUCCESS_TEAM),
            ("Amara Singh", "amara", User.Role.SPECIALIST, User.TeamRole.SPECIALIST),
            ("Lena Vogt", "lena", User.Role.VIEWER, User.TeamRole.MEDIA_CONTACT),
        ]
        out = []
        for name, handle, role, team_role in members:
            email = f"{handle}@{DEMO_DOMAIN}"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "name": name,
                    "role": role,
                    "team_role": team_role,
                    "is_active": True,
                    "is_staff": False,
                },
            )
            if created:
                user.set_password(ADMIN_PASSWORD)
                user.save()
            out.append(user)
        self.stdout.write(self.style.SUCCESS(f"  team members: {len(out)}"))
        return out

    # ── leads ────────────────────────────────────────────────────────────────
    def _lead_specs(self) -> list[dict]:
        """One dict per lead. ``age_days`` drives submitted_at; status sets the stage."""
        return [
            dict(company="Helion Silicon", name="Evelyn Park", role="CTO / Chief Scientist",
                 industry="Semiconductor / AI chip", status=LeadStatus.NEW, score=88, tier=1,
                 route=ProductRouteCode.ALPHA_CORE, path=CommercialPathCode.EXCLUSIVE,
                 rights=SpecialRights.FIELD, pain="Speed", age_days=0,
                 bottleneck="Chip needs a stronger software stack to differentiate on real workloads.",
                 intent="Field-of-use licensing", timeline="Within 3 months"),
            dict(company="NimbusScale", name="Marcus Lee", role="Product / Platform Owner",
                 industry="Cloud / hyperscaler / data center", status=LeadStatus.NEW, score=71, tier=2,
                 route=ProductRouteCode.ALPHA_COMPUTE, path=CommercialPathCode.NON_EXCLUSIVE,
                 rights=SpecialRights.NONE, pain="Energy", age_days=0,
                 bottleneck="Energy and cooling are capping AI expansion; need better compute density.",
                 intent="Confidential evaluation", timeline="Within 6 months"),
            dict(company="Aerodyne CAE", name="Priya Nair", role="Solver / Simulation Team",
                 industry="HPC / CAE / simulation", status=LeadStatus.CONTACTED, score=64, tier=2,
                 route=ProductRouteCode.ALPHA_COMPUTE, path=CommercialPathCode.NON_EXCLUSIVE,
                 rights=SpecialRights.NONE, pain="Accuracy", age_days=3,
                 bottleneck="Conservation-law simulation loses accuracy over long time runs.",
                 intent="Paid PoC", timeline="Within 3 months"),
            dict(company="Kernighan Labs", name="Tom Becker", role="Engineering / Runtime / SDK",
                 industry="AI infrastructure / compiler / runtime", status=LeadStatus.CONTACTED, score=58, tier=3,
                 route=ProductRouteCode.ALPHA_CORE, path=CommercialPathCode.NONE,
                 rights=SpecialRights.NONE, pain="Reproducibility", age_days=5,
                 bottleneck="Solver runtime and reproducibility are blocking a production rollout.",
                 intent="SDK / runtime integration", timeline="Within 12 months"),
            dict(company="Voltaire Grid", name="Camille Dubois", role="Strategy / Corporate Development",
                 industry="Energy / infrastructure", status=LeadStatus.MEETING_BOOKED, score=82, tier=1,
                 route=ProductRouteCode.BOTH, path=CommercialPathCode.STRATEGIC,
                 rights=SpecialRights.TERRITORY, pain="Energy", age_days=8,
                 bottleneck="Energy and cooling are capping AI expansion; need better compute density.",
                 intent="Strategic investment", timeline="Within 6 months"),
            dict(company="Synapse Robotics", name="Kenji Sato", role="CTO / Chief Scientist",
                 industry="Robotics / edge AI", status=LeadStatus.MEETING_BOOKED, score=69, tier=2,
                 route=ProductRouteCode.ALPHA_COMPUTE, path=CommercialPathCode.NON_EXCLUSIVE,
                 rights=SpecialRights.NONE, pain="Memory", age_days=10,
                 bottleneck="Edge device can't fit the workload within power and latency limits.",
                 intent="Paid PoC", timeline="Within 3 months"),
            dict(company="Meridian Ventures", name="Olivia Grant", role="Investor",
                 industry="Investment / corporate development", status=LeadStatus.NDA, score=76, tier=2,
                 route=ProductRouteCode.GENERAL, path=CommercialPathCode.STRATEGIC,
                 rights=SpecialRights.ACQUISITION, pain="Speed", age_days=14,
                 bottleneck="Evaluating iTrix as a strategic compute-IP position.",
                 intent="Acquisition / partnership", timeline="Within 12 months"),
            dict(company="KAIST CCL", name="Dr. Han Soo-jin", role="Researcher",
                 industry="Research / public institution", status=LeadStatus.NDA, score=61, tier=3,
                 route=ProductRouteCode.ALPHA_CORE, path=CommercialPathCode.NON_EXCLUSIVE,
                 rights=SpecialRights.NONE, pain="Accuracy", age_days=18,
                 bottleneck="Complex-valued computation is inefficient on real hardware.",
                 intent="Confidential evaluation", timeline="Long-term research"),
            dict(company="Pascal Systems", name="Greg Holt", role="Engineering / Runtime / SDK",
                 industry="AI infrastructure / compiler / runtime", status=LeadStatus.EVALUATION, score=79, tier=1,
                 route=ProductRouteCode.ALPHA_COMPUTE, path=CommercialPathCode.NON_EXCLUSIVE,
                 rights=SpecialRights.NONE, pain="Speed", age_days=22,
                 bottleneck="AI inference cost is rising; GPU-hour spend nearly doubled in six months.",
                 intent="Paid PoC", timeline="Within 3 months"),
            dict(company="Tonghae Cloud", name="Min-jun Kim", role="Product / Platform Owner",
                 industry="Cloud / hyperscaler / data center", status=LeadStatus.EVALUATION, score=73, tier=2,
                 route=ProductRouteCode.BOTH, path=CommercialPathCode.EXCLUSIVE,
                 rights=SpecialRights.PRODUCT_CATEGORY, pain="Energy", age_days=26,
                 bottleneck="Memory movement dominates runtime in the inference path.",
                 intent="Field-of-use licensing", timeline="Within 6 months"),
            dict(company="Fermi Compute", name="Anita Rao", role="CEO / Founder / Executive",
                 industry="HPC / CAE / simulation", status=LeadStatus.POC, score=85, tier=1,
                 route=ProductRouteCode.ALPHA_COMPUTE, path=CommercialPathCode.NON_EXCLUSIVE,
                 rights=SpecialRights.NONE, pain="Speed", age_days=33,
                 bottleneck="Scientific simulation runtime is blocking a production rollout.",
                 intent="Paid PoC", timeline="Immediately"),
            dict(company="BlueShift HPC", name="Erik Lund", role="Solver / Simulation Team",
                 industry="HPC / CAE / simulation", status=LeadStatus.POC, score=80, tier=1,
                 route=ProductRouteCode.BOTH, path=CommercialPathCode.STRATEGIC,
                 rights=SpecialRights.TERRITORY, pain="Accuracy", age_days=40,
                 bottleneck="Conservation-law simulation loses accuracy over long time runs.",
                 intent="Strategic investment", timeline="Within 3 months"),
            dict(company="Cixi Semiconductors", name="Wei Zhang", role="CTO / Chief Scientist",
                 industry="Semiconductor / AI chip", status=LeadStatus.LICENSED, score=91, tier=1,
                 route=ProductRouteCode.ALPHA_CORE, path=CommercialPathCode.EXCLUSIVE,
                 rights=SpecialRights.EXCLUSIVE_GLOBAL, pain="Speed", age_days=55,
                 bottleneck="Chip needs a stronger software stack to differentiate on real workloads.",
                 intent="Field-of-use licensing", timeline="Immediately"),
            dict(company="Northwind Energy", name="Sarah Whitman", role="Strategy / Corporate Development",
                 industry="Energy / infrastructure", status=LeadStatus.CLOSED, score=44, tier=4,
                 route=ProductRouteCode.GENERAL, path=CommercialPathCode.NONE,
                 rights=SpecialRights.NONE, pain="Energy", age_days=60,
                 bottleneck="Exploratory interest, no near-term compute initiative.",
                 intent="Learning about iTrix", timeline="Long-term research"),
            dict(company="Atlas Foundry", name="Pedro Alvarez", role="Product / Platform Owner",
                 industry="Semiconductor / AI chip", status=LeadStatus.NURTURE, score=52, tier=3,
                 route=ProductRouteCode.ALPHA_COMPUTE, path=CommercialPathCode.NONE,
                 rights=SpecialRights.NONE, pain="Hardware independence", age_days=30,
                 bottleneck="Wants hardware-independent acceleration but timeline is unclear.",
                 intent="Learning about iTrix", timeline="Within 12 months"),
            dict(company="Quanta Dynamics", name="Hana Yoshida", role="CTO / Chief Scientist",
                 industry="AI infrastructure / compiler / runtime", status=LeadStatus.NEGOTIATION, score=83, tier=1,
                 route=ProductRouteCode.BOTH, path=CommercialPathCode.EXCLUSIVE,
                 rights=SpecialRights.TIME_LIMITED, pain="Speed", age_days=48,
                 bottleneck="Finalising an exclusive field-of-use licence terms.",
                 intent="Field-of-use licensing", timeline="Within 3 months"),
        ]

    def _seed_leads(self, owners: list["User"]) -> list[Lead]:
        leads = []
        specs = self._lead_specs()
        sla = SlaThresholds.load()
        tier_hours = {1: sla.tier1_hours, 2: sla.tier2_hours, 3: sla.tier3_hours, 4: sla.tier4_hours}
        for i, s in enumerate(specs):
            owner = owners[i % len(owners)]
            email = f"{s['name'].split()[0].lower()}@{s['company'].lower().replace(' ', '')}.example.com"
            submitted = self.now - _d(s["age_days"]) - _h(i)
            due_hours = tier_hours.get(s["tier"])
            lead, _ = Lead.objects.get_or_create(
                email=email,
                company=s["company"],
                defaults=dict(
                    visitor_name=s["name"],
                    role=s["role"],
                    industry=s["industry"],
                    product_route=s["route"],
                    commercial_path=s["path"],
                    special_rights=s["rights"],
                    compute_bottleneck=s["bottleneck"],
                    primary_pain=s["pain"],
                    workload_type=s["industry"],
                    current_stack=["GPU", "CUDA / ROCm / oneAPI", "PyTorch / JAX / TensorFlow"],
                    commercial_intent=s["intent"],
                    timeline=s["timeline"],
                    score=s["score"],
                    tier=s["tier"],
                    score_breakdown={
                        "Strategic fit": round(s["score"] * 0.28),
                        "Technical fit": round(s["score"] * 0.26),
                        "Commercial readiness": round(s["score"] * 0.2),
                        "Urgency": round(s["score"] * 0.14),
                        "Authority": round(s["score"] * 0.12),
                    },
                    recommended_next_step="Book a confidential technical review call.",
                    human_handoff_trigger=s["tier"] == 1,
                    qualification={
                        "primary_pain": s["pain"],
                        "timeline": s["timeline"],
                        "commercial_intent": s["intent"],
                    },
                    status=s["status"],
                    owner=owner,
                    cta_clicked="book_meeting" if s["tier"] <= 2 else "view_technology",
                    documents_viewed=max(0, 6 - i % 6),
                    sla_response_due_at=(submitted + _h(due_hours)) if due_hours else None,
                    first_response_at=(submitted + _h(2)) if s["status"] != LeadStatus.NEW else None,
                    escalated=s["status"] == LeadStatus.NEW and s["tier"] == 1 and s["age_days"] == 0,
                ),
            )
            # submitted_at is auto_now_add; set it explicitly for spread-out demo data.
            if lead.submitted_at != submitted:
                Lead.objects.filter(pk=lead.pk).update(submitted_at=submitted)
                lead.submitted_at = submitted
            leads.append(lead)
        self.stdout.write(self.style.SUCCESS(f"  leads: {len(leads)}"))
        return leads

    def _seed_lead_timeline(self, leads: list[Lead], admin: "User"):
        activities = 0
        notes = 0
        for lead in leads:
            by = lead.owner or admin
            _, c1 = LeadActivity.objects.get_or_create(
                lead=lead,
                type=LeadActivity.ActivityType.SUBMISSION,
                defaults=dict(label=f"Lead submitted via review ({lead.tier and f'Tier {lead.tier}'})",
                              by=by, by_name=by.display_name),
            )
            activities += int(c1)
            if lead.status != LeadStatus.NEW:
                _, c2 = LeadActivity.objects.get_or_create(
                    lead=lead,
                    type=LeadActivity.ActivityType.STATUS_CHANGE,
                    label=f"Status moved to {lead.status}",
                    defaults=dict(by=by, by_name=by.display_name,
                                  meta={"to": lead.status}),
                )
                activities += int(c2)
            # A note on a few leads.
            if lead.tier == 1:
                _, cn = LeadNote.objects.get_or_create(
                    lead=lead,
                    body=f"High-priority {lead.company} — fast-track technical review.",
                    defaults=dict(author=by, author_name=by.display_name),
                )
                notes += int(cn)

        # One concrete meeting on a Meeting Booked lead.
        booked = next((l for l in leads if l.status == LeadStatus.MEETING_BOOKED), None)
        meetings = 0
        if booked:
            by = booked.owner or admin
            _, cm = LeadMeeting.objects.get_or_create(
                lead=booked,
                attendee=booked.visitor_name,
                defaults=dict(
                    scheduled_at=self.now + _d(2),
                    duration_mins=45,
                    location="Google Meet",
                    notes="Confidential technical review of the ALPHA fit.",
                    booked_by=by,
                    booked_by_name=by.display_name,
                ),
            )
            meetings += int(cm)
            LeadActivity.objects.get_or_create(
                lead=booked,
                type=LeadActivity.ActivityType.MEETING,
                label="Technical review meeting booked",
                defaults=dict(by=by, by_name=by.display_name),
            )
        self.stdout.write(self.style.SUCCESS(
            f"  activities: +{activities}, notes: +{notes}, meetings: +{meetings}"))

    # ── stage artifacts (NDA / Evaluation / PoC) ──────────────────────────────
    def _seed_stage_artifacts(self, leads: list[Lead]):
        nda_n = ev_n = poc_n = 0
        # Statuses at-or-beyond a stage get the artifact for every earlier stage too.
        nda_or_beyond = {LeadStatus.NDA, LeadStatus.EVALUATION, LeadStatus.POC,
                         LeadStatus.LICENSED, LeadStatus.NEGOTIATION}
        eval_or_beyond = {LeadStatus.EVALUATION, LeadStatus.POC, LeadStatus.LICENSED,
                          LeadStatus.NEGOTIATION}
        poc_or_beyond = {LeadStatus.POC, LeadStatus.LICENSED, LeadStatus.NEGOTIATION}

        for lead in leads:
            if lead.status in nda_or_beyond:
                nda = create_nda_for_lead(lead)
                # Vary NDA status across the demo set.
                if lead.status == LeadStatus.NDA and lead.tier and lead.tier >= 3:
                    self._set_nda(nda, NDAStatus.SENT, signer=lead.visitor_name, email=lead.email)
                elif lead.status == LeadStatus.NDA:
                    pass  # leave at REQUIRED for the freshly-arrived NDA
                else:
                    self._set_nda(nda, NDAStatus.SIGNED, signer=lead.visitor_name, email=lead.email)
                nda_n += 1
            if lead.status in eval_or_beyond:
                # The creator is only idempotent for an *open* eval; once we advance the
                # status it would create a duplicate on re-run. Reuse any existing one.
                ev = Evaluation.objects.filter(lead=lead).first() or create_evaluation_for_lead(lead)
                if lead.status in poc_or_beyond and ev.status != EvaluationStatus.DELIVERED:
                    ev.status = EvaluationStatus.DELIVERED
                    ev.save(update_fields=["status"])
                ev_n += 1
            if lead.status in poc_or_beyond:
                poc = PoC.objects.filter(lead=lead).first() or create_poc_for_lead(lead)
                if lead.status == LeadStatus.LICENSED:
                    poc.status = PoCStatus.COMPLETED
                else:
                    poc.status = PoCStatus.ACTIVE
                poc.risks = [{
                    "id": 1,
                    "description": "Integration effort into the existing stack may exceed the window.",
                    "severity": "medium",
                    "mitigation": "Pair with the Technical Review Team for the first sprint.",
                }]
                poc.save(update_fields=["status", "risks"])
                poc_n += 1
        self.stdout.write(self.style.SUCCESS(f"  NDAs: {nda_n}, evaluations: {ev_n}, PoCs: {poc_n}"))

    def _set_nda(self, nda: NDARecord, status, *, signer="", email=""):
        nda.status = status
        nda.signer_name = signer
        nda.signer_email = email
        nda.doc_type = nda.doc_type or "mutual"
        if not nda.body:
            nda.body = (
                "MUTUAL NON-DISCLOSURE AGREEMENT\n\n"
                "This Agreement governs the exchange of confidential information between "
                "IWL / iTrix and the counterparty for the purpose of evaluating the ALPHA "
                "compute technology."
            )
        if status in (NDAStatus.SENT, NDAStatus.SIGNED):
            nda.sent_at = self.now - _d(2)
        if status == NDAStatus.SIGNED:
            nda.signed_at = self.now - _d(1)
            nda.checklist = [{**c, "done": True} for c in nda.checklist]
        nda.save()

    # ── follow-ups ─────────────────────────────────────────────────────────────
    def _seed_follow_ups(self, leads: list[Lead], owners: list["User"]):
        # Anchor specific cases to known leads/statuses for the demo.
        open_leads = [l for l in leads if l.status not in
                      {LeadStatus.LICENSED, LeadStatus.CLOSED, LeadStatus.LOST}]
        plan = []
        if open_leads:
            plan.append((open_leads[0], self.now - _d(2), FollowUpStatus.PENDING,
                         "Overdue: first-response SLA breached."))      # OVERDUE
        if len(open_leads) > 1:
            plan.append((open_leads[1], self.now + _h(3), FollowUpStatus.PENDING,
                         "Due today: send the evaluation proposal."))    # DUE TODAY
        if len(open_leads) > 2:
            plan.append((open_leads[2], self.now + _d(2), FollowUpStatus.PENDING,
                         "Upcoming: follow up after the review call."))
        if len(open_leads) > 3:
            plan.append((open_leads[3], self.now + _d(5), FollowUpStatus.PENDING,
                         "Upcoming: check NDA signature status."))
        if len(open_leads) > 4:
            t = (open_leads[4], self.now - _d(1), FollowUpStatus.SNOOZED,
                 "Snoozed: lead asked to reconnect next week.")
            plan.append(t)

        count = 0
        for lead, due_at, status, note in plan:
            task, created = FollowUpTask.objects.get_or_create(
                lead=lead,
                note=note,
                defaults=dict(
                    lead_name=lead.company or lead.visitor_name,
                    company=lead.company,
                    tier=lead.tier or 4,
                    owner=lead.owner,
                    due_at=due_at,
                    status=status,
                    snoozed_until=(self.now + _d(7)) if status == FollowUpStatus.SNOOZED else None,
                ),
            )
            count += int(created)
        # A couple of completed ones for history.
        for lead in [l for l in leads if l.status in {LeadStatus.LICENSED, LeadStatus.POC}][:2]:
            _, c = FollowUpTask.objects.get_or_create(
                lead=lead,
                note="Completed: kickoff scheduled.",
                defaults=dict(
                    lead_name=lead.company, company=lead.company, tier=lead.tier or 4,
                    owner=lead.owner, due_at=self.now - _d(3),
                    status=FollowUpStatus.COMPLETED, completed_at=self.now - _d(3),
                ),
            )
            count += int(c)
        self.stdout.write(self.style.SUCCESS(f"  follow-up tasks: +{count}"))

    # ── notifications ──────────────────────────────────────────────────────────
    def _seed_notifications(self, leads: list[Lead]):
        by_status = {l.status: l for l in leads}
        tier1 = next((l for l in leads if l.tier == 1), None)
        new_lead = by_status.get(LeadStatus.NEW)
        signed = next((l for l in leads if l.status in
                       {LeadStatus.EVALUATION, LeadStatus.POC, LeadStatus.LICENSED}), None)
        specs = [
            (Notification.Kind.NEW_LEAD, "New lead captured",
             f"{new_lead.company if new_lead else 'A new company'} just completed the review.",
             new_lead, False),
            (Notification.Kind.TIER1_LEAD, "Tier 1 lead requires attention",
             f"{tier1.company if tier1 else 'A Tier 1 lead'} scored in the top tier.",
             tier1, False),
            (Notification.Kind.SLA_BREACH, "SLA breach",
             "A first-response SLA has been breached.", new_lead, True),
            (Notification.Kind.NDA_SIGNED, "NDA signed",
             f"{signed.company if signed else 'A counterparty'} signed the mutual NDA.",
             signed, False),
            (Notification.Kind.ESCALATION, "Lead escalated",
             "A high-value lead was escalated to the Expert Concierge.", tier1, True),
            (Notification.Kind.SYSTEM, "[Demo] Demo data loaded",
             "Seed data for the live demo is ready.", None, True),
        ]
        count = 0
        for kind, title, body, lead, read in specs:
            _, created = Notification.objects.get_or_create(
                kind=kind,
                title=title,
                lead=lead,
                defaults=dict(body=body, read=read, href="/leads" if lead else ""),
            )
            count += int(created)
        self.stdout.write(self.style.SUCCESS(f"  notifications: +{count}"))

    # ── templates ──────────────────────────────────────────────────────────────
    def _seed_templates(self):
        templates = [
            (TemplateKind.EMAIL, "[Demo] First-response email",
             "Subject: iTrix — following up on {{company}}'s compute review\n\n"
             "Hi {{contact_name}},\n\nThanks for completing the iTrix review. Based on your "
             "{{primary_pain}} bottleneck, I'd love to set up a confidential technical call.\n\n"
             "Best,\n{{owner_name}}"),
            (TemplateKind.FOLLOW_UP, "[Demo] Follow-up nudge",
             "Subject: Checking in — {{company}}\n\n"
             "Hi {{contact_name}}, just following up on the {{next_step}} for {{company}}. "
             "Are you free this week?\n\n{{owner_name}}"),
            (TemplateKind.EVALUATION, "[Demo] Evaluation proposal",
             "Subject: Proposed evaluation for {{company}}\n\n"
             "We propose the {{package}} evaluation, targeting your {{primary_pain}} KPIs "
             "over a {{timeline}} window.\n\nKPIs: {{kpi_list}}"),
            (TemplateKind.POC, "[Demo] PoC kickoff",
             "Subject: PoC kickoff — {{company}}\n\n"
             "Welcome to the {{company}} PoC. First milestone: {{milestone}}, due {{due_date}}. "
             "Owner: {{owner_name}}."),
            (TemplateKind.HANDOFF, "[Demo] Internal handoff",
             "Subject: Handoff — {{company}} ({{tier}})\n\n"
             "Handing {{company}} to {{new_owner}}. Status: {{status}}. Context: {{notes}}."),
        ]
        count = 0
        for kind, name, body in templates:
            _, created = Template.objects.get_or_create(
                kind=kind, name=name, defaults=dict(body=body)
            )
            count += int(created)
        self.stdout.write(self.style.SUCCESS(f"  templates: +{count}"))

    # ── monthly report ─────────────────────────────────────────────────────────
    def _report_month(self) -> str:
        return self.now.strftime("%Y-%m")

    def _seed_report(self):
        month = self._report_month()
        sections = [
            {"id": 1, "title": "Pipeline overview",
             "body": "16 active leads across the pipeline, with 5 Tier-1 opportunities. "
                     "Two PoCs are in flight and one licence closed this month."},
            {"id": 2, "title": "SLA & responsiveness",
             "body": "Median first-response time was under 4 hours for Tier-1 leads. "
                     "One SLA breach was escalated and recovered."},
            {"id": 3, "title": "Conversions",
             "body": "Evaluation→PoC conversion held at ~50%. Cixi Semiconductors moved to "
                     "an exclusive global licence."},
            {"id": 4, "title": "Next month focus",
             "body": "Close the Quanta Dynamics negotiation and convert two evaluations to PoCs."},
        ]
        _, created = MonthlyReport.objects.get_or_create(
            month=month, defaults=dict(sections=sections)
        )
        self.stdout.write(self.style.SUCCESS(
            f"  monthly report: {'+1' if created else 'exists'} ({month})"))

    def _seed_sla(self):
        SlaThresholds.load()  # creates the singleton with defaults if absent
        self.stdout.write(self.style.SUCCESS("  SLA thresholds: ensured"))

    # ── summary ────────────────────────────────────────────────────────────────
    def _summary(self, admin):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Demo data seeded."))
        self.stdout.write("  Counts:")
        for label, model in [
            ("team members", User), ("leads", Lead), ("activities", LeadActivity),
            ("meetings", LeadMeeting), ("NDAs", NDARecord), ("evaluations", Evaluation),
            ("PoCs", PoC), ("follow-ups", FollowUpTask), ("notifications", Notification),
            ("templates", Template), ("reports", MonthlyReport),
        ]:
            self.stdout.write(f"    {label:<16}: {model.objects.count()}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("  Login credentials (dashboard):"))
        self.stdout.write(self.style.SUCCESS(f"    email   : {ADMIN_EMAIL}"))
        self.stdout.write(self.style.SUCCESS(f"    password: {ADMIN_PASSWORD}"))
