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
        self._seed_governance(leads, admin, team)
        self._seed_conversation_threads(leads, admin)
        self._seed_astop(leads)

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

        # Governance/operations records. Conversations cascade off Lead, but
        # ApprovalRequest.lead is SET_NULL and ClaimCard has no lead at all, so both
        # would survive the flush as orphans. Remove the demo rows explicitly.
        from apps.conversations.models import Conversation
        from apps.governance.models import ApprovalRequest, ClaimCard

        Conversation.objects.filter(title__startswith="[Demo]").delete()  # cascades messages
        ClaimCard.objects.filter(key__startswith="demo_").delete()
        ApprovalRequest.objects.filter(
            agent_key__in=["proof", "objection", "proposal"], lead__isnull=True
        ).delete()

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

    # ── governance & operations (console, approvals, claim-cards) ──────────────
    def _seed_governance(self, leads, admin, team):
        """
        Seed the operator surfaces that otherwise render empty: the Claim-Card
        library, two client conversations, and an approval queue that exercises the
        single-approver (L3) and two-approver (L4/L5) paths.

        Without this, Console / Approvals / Claim-Cards / Audit all show empty states,
        because nothing in the funnel creates them: agents below the auto-approve
        threshold (L1–L2) never queue an approval, and conversations only appear when
        a real visitor chats through Surface 1.
        """
        from apps.conversations.models import (
            Conversation,
            ConversationContext,
            GovernanceStatus,
            Message,
            SenderKind,
        )
        from apps.governance.models import ApprovalRequest, ApprovalStatus, ClaimCard, ClaimLevel

        # A second elevated approver so the L4/L5 two-approver rule is satisfiable.
        second = next((u for u in team if u.role == User.Role.ASSESSMENT), None)

        # 1) Claim-Card library — the approved wording agents are checked against.
        cards = [
            # Product/technology definitions are deliberately not seeded as Claim Cards.
            # They are resolved through the current authorized source hierarchy so demo
            # data cannot resurrect superseded canonical wording.
            ("demo_sustainable_ai", "[Demo] Sustainable AI positioning",
             "itriX builds Computational AI Infrastructure for Sustainable AI.", ClaimLevel.L1,
             "Approved public one-liner."),
            ("demo_axiom_spd", "[Demo] AXIOM SPD / Cholesky speedup",
             "May reduce cost and improve speed for specific SPD/Cholesky workloads. "
             "Specific ratios are internal-only until approved.", ClaimLevel.L3,
             "The 3–4x figure is INTERNAL-ONLY. Cite before any external use."),
            ("demo_energy_roi", "[Demo] Energy reduction (ROI)",
             "Potential energy reduction for eligible workloads, validated through evaluation.",
             ClaimLevel.L4, "Commercial/ROI — mandatory approval, never auto-delivered."),
        ]
        n_cards = 0
        for key, title, wording, level, notes in cards:
            _, created = ClaimCard.objects.get_or_create(
                key=key,
                defaults=dict(
                    title=title, approved_wording=wording, claim_level=level,
                    owner=admin, is_active=True, notes=notes,
                ),
            )
            n_cards += int(created)

        # 2) Two conversations with real message history, tied to demo leads.
        convos = []
        seeds = [
            (ConversationContext.REVIEW, "[Demo] Cloud AI compute cost", [
                (SenderKind.CLIENT, "", "Our inference bill is growing faster than usage. "
                                        "Where does the waste come from?"),
                (SenderKind.AGENT, "diagnosis",
                 "Rising spend usually traces to redundant computation entering at the "
                 "representation layer, before kernels run. A short review can map where."),
            ]),
            (ConversationContext.PORTAL, "[Demo] Semiconductor SDK partner", [
                (SenderKind.CLIENT, "", "Can you share the benchmark harness so our team "
                                        "can reproduce it?"),
                (SenderKind.TEAM, "", "We can share the harness under NDA — I'll prepare the "
                                      "paperwork and follow up."),
            ]),
        ]
        for i, (context, title, msgs) in enumerate(seeds):
            lead = leads[i] if i < len(leads) else None
            conv, created = Conversation.objects.get_or_create(
                title=title,
                defaults=dict(context=context, lead=lead, is_active=True, last_message_at=self.now),
            )
            if created:
                for kind, agent_key, body in msgs:
                    Message.objects.create(
                        conversation=conv, sender_kind=kind, agent_key=agent_key, body=body,
                        governance_status=GovernanceStatus.AUTO_APPROVED, claim_level=1,
                    )
            convos.append(conv)

        # 3) Approval queue — one L3 (single approver), one L4 already awaiting its
        #    second approver, and one L5 legal draft.
        approvals = [
            ("proof", ClaimLevel.L3, ApprovalStatus.PENDING, None,
             "In an internal SPD/Cholesky benchmark, the real-block representation reduced "
             "solve time by roughly 3–4x. We can share the harness under NDA.",
             ["wp_alpha_secret_001", "axiom_benchmark_003"], convos[0]),
            ("objection", ClaimLevel.L4, ApprovalStatus.AWAITING_SECOND, admin,
             "On ROI: partners typically model payback against GPU-hour and energy savings; "
             "a paid assessment quantifies the candidate reduction for your workload before "
             "any commitment.",
             ["commercialization_007"], convos[0]),
            ("proposal", ClaimLevel.L5, ApprovalStatus.PENDING, None,
             "Draft LOI: itriX grants a 24-month field-exclusive license for the semiconductor "
             "SDK, with a minimum guarantee and milestone schedule as discussed.",
             ["commercial_pathway_012"], convos[1]),
        ]
        n_appr = 0
        for agent_key, level, status, first, body, chunks, conv in approvals:
            _, created = ApprovalRequest.objects.get_or_create(
                agent_key=agent_key,
                draft_body=body,
                defaults=dict(
                    lead=conv.lead, conversation_id=str(conv.id), claim_level=level,
                    cited_chunk_ids=chunks, status=status, first_approver=first,
                ),
            )
            n_appr += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"  claim cards: +{n_cards}, conversations: {len(convos)}, approvals: +{n_appr}"))
        if second is None:
            self.stdout.write(self.style.WARNING(
                "  note: no second ASSESSMENT approver — L4/L5 drafts cannot be fully approved"))

    # ── summary ────────────────────────────────────────────────────────────────
    # -- conversations (the thread board) -------------------------------------
    def _seed_conversation_threads(self, leads, admin):
        """
        Threads for the cockpit conversation board.

        Nothing else in this seeder creates a Thread - ``_seed_governance`` creates
        Conversations and Messages, which are different models - so the board rendered
        empty and the four state fields it now shows had nothing to show.

        Three things are deliberately demonstrated, because each is a real property of
        the model that one tidy thread per lead would hide:

        1. **One lead, several conversations, in different states.** ``Thread.lead`` is a
           FK. A lead can be mid-assessment in one chat and an anonymous browser in
           another, and the board must show that rather than average it away.
        2. **Anonymous threads.** No lead and no client: the population with no lead page
           to live on, which is the board's actual job.
        3. **A confirmed Problem Mirror, and one still pending.** ``mirror_status`` gates
           what the AI may recommend, so the difference is load-bearing, not cosmetic.
        """
        from apps.conversations.models import Thread
        from apps.conversations.services import threads as thread_svc

        attributed = [
            (0, "Cholesky throughput on the new part", "customer", "confirmed",
             "assessment", "ASSESSMENT", [
                 ("v", "We are taping out a new accelerator and the software stack is the "
                       "differentiator. Where does itriX fit?"),
                 ("a", "Before any route, let me restate your situation in six parts."),
                 ("v", "That reflects it. Part 3 is the one that matters to us."),
                 ("a", "Understood - recorded. Structural eligibility comes next."),
             ]),
            (0, "Follow-up: does this cover the FP8 path", "visitor", "pending",
             "exploration", "IN_REVIEW", [
                 ("v", "Separate question from a colleague - does any of this apply to FP8?"),
                 ("a", "It may. Let me reflect the workload back before answering."),
             ]),
            (1, "Energy per token, not per rack", "customer", "confirmed",
             "assessment", "ASSESSMENT", [
                 ("v", "Cooling is capping expansion. We measure energy per rack; I think "
                       "the number we actually need is per token."),
                 ("a", "That distinction is the reflection's Part 1. Confirming it now."),
                 ("v", "Confirmed."),
             ]),
            (2, "Conservation-law drift over long runs", "technical_evaluator",
             "not_required", "exploration", "IN_REVIEW", [
                 ("v", "Our simulation loses accuracy over long time runs. Is that a "
                       "representation problem or a solver problem?"),
                 ("a", "Those are different failures with different evidence. Which one "
                       "shows up first in your runs?"),
             ]),
            (3, "Runtime reproducibility before rollout", "visitor", "refine",
             "exploration", "IN_REVIEW", [
                 ("v", "Reproducibility is blocking a production rollout."),
                 ("a", "Restating: the blocker is run-to-run variance, not absolute speed."),
                 ("v", "Not quite - it is both, but variance is what stops sign-off."),
             ]),
        ]

        made = 0
        for idx, title, relationship, mirror, stage, state, turns in attributed:
            if idx >= len(leads):
                continue
            lead = leads[idx]

            # The board resolves a company from the CLIENT record only - never from
            # anything the visitor typed, which is why `Lead.company` is deliberately not
            # used there. So a conversation that has genuinely reached a customer
            # relationship needs the workspace that relationship implies, or it shows up
            # correctly attributed and namelessly blank.
            # A customer relationship implies a workspace, so create one. A mere visitor
            # does not - but if this lead already has a workspace, their other
            # conversations belong to it rather than looking unattributed.
            if relationship in ("customer", "strategic_customer"):
                client = self._workspace_for(lead)
            else:
                from apps.clients.models import Client as _Client
                client = _Client.objects.filter(lead=lead).first()

            thread = Thread.objects.filter(lead=lead, title=title).first()
            if thread is None:
                thread = thread_svc.create_thread(
                    visitor_session="demo-sess-%s-%s" % (lead.id, title[:12]),
                    lead=lead,
                    client=client,
                    title=title,
                )
                made += 1
            thread.lead = lead
            if client is not None and thread.client_id != client.id:
                thread.client = client
            thread.relationship_state = relationship
            thread.mirror_status = mirror
            thread.engagement_stage = stage
            thread.current_state = state
            thread.last_activity_at = self.now - _h(idx + 1)
            thread.save(update_fields=[
                "lead", "client", "relationship_state", "mirror_status",
                "engagement_stage", "current_state", "last_activity_at", "updated_at",
            ])
            self._turns(thread, turns)

        anonymous = [
            ("Inference cost rising faster than usage", [
                ("v", "Our inference costs are rising faster than our usage and I need to "
                      "know whether that is a hardware problem or a pipeline problem "
                      "before our budget review next month."),
                ("a", "That is a decision, not just a symptom - which makes it a good "
                      "starting point. Let me restate it before suggesting anything."),
            ]),
            ("What does itriX actually do", [
                ("v", "What does itriX do, in plain terms?"),
                ("a", "We work on the representation of computation - how work is shaped "
                      "before it runs."),
            ]),
            ("Can I read the evidence first", [
                ("v", "What published or validated evidence can I review without starting "
                      "a commercial process?"),
            ]),
        ]
        for title, turns in anonymous:
            thread = Thread.objects.filter(title=title, lead__isnull=True).first()
            if thread is None:
                thread = thread_svc.create_thread(
                    visitor_session="demo-anon-%s" % title[:14], title=title,
                )
                made += 1
            thread.last_activity_at = self.now - _h(1)
            thread.save(update_fields=["last_activity_at", "updated_at"])
            self._turns(thread, turns)

        self._link_transition_provenance(leads)
        self.stdout.write("  conversations: %s new thread(s)" % made)

    def _workspace_for(self, lead):
        """
        The Client record for a lead that has reached a customer relationship.

        ``advance_journey=False``: ``ACCEPT_INVITE`` is only legal from ``INVITED``, and
        these demo leads sit wherever their own spec put them. Creating a workspace here
        is a seeding convenience, not a journey event, and it must not log a failed
        advance on every run.
        """
        from apps.clients.models import Client
        from apps.clients.services.client_creator import create_client_for_lead

        existing = Client.objects.filter(lead=lead).first()
        if existing is not None:
            return existing
        try:
            client, _ = create_client_for_lead(
                lead,
                email=lead.email,
                full_name=getattr(lead, "visitor_name", "") or "",
                organization=lead.company or "",
                role=getattr(lead, "role", "") or "",
                advance_journey=False,
            )
            return client
        except Exception as exc:  # noqa: BLE001 - a demo workspace never fails the seed
            # Reported, not swallowed. A silent except here hid a plain AttributeError
            # for a whole run and the board simply showed blank companies.
            self.stdout.write(self.style.WARNING(
                "  workspace for %s skipped: %s" % (lead.company, exc)
            ))
            return None

    def _turns(self, thread, turns):
        """Idempotent message fill. Seq is 1-based and stable, so a re-run is a no-op."""
        from apps.conversations.models import Message, SenderKind

        conversation = thread.conversation
        if conversation is None:
            return
        for i, (who, body) in enumerate(turns, start=1):
            Message.objects.get_or_create(
                conversation=conversation,
                thread=thread,
                seq=i,
                defaults=dict(
                    sender_kind=SenderKind.VISITOR if who == "v" else SenderKind.AGENT,
                    body=body,
                ),
            )

    def _link_transition_provenance(self, leads):
        """
        Produce transitions that actually carry their conversation.

        Driven through ``journey.advance(..., thread=...)`` rather than by writing rows,
        for two reasons. State has exactly one writer (Architecture v2.6 section 11.9),
        so a seeder that inserts JourneyTransition directly is seeding a shape the app
        can never produce. And routing it through ``advance`` is what proves the new
        ``thread`` column is populated by the real path, not only by the migration's
        backfill.

        Only demo leads are touched. Any pre-existing lead in the database keeps its own
        history: a seeder that rewrites rows it did not create is not idempotent, it is
        destructive.
        """
        from apps.conversations.models import Thread
        from apps.journey.models import JourneyEvent, JourneyState
        from apps.journey.services.advance import InvalidTransition, advance

        made = 0
        for lead in leads:
            threads = list(
                Thread.objects.filter(lead=lead).order_by("-last_activity_at", "-created_at")
            )
            if not threads:
                continue
            # The conversation that EARNED the stage, not merely the most recent one. A
            # lead can have a confirmed reflection in one chat and an idle question in
            # another; attributing the advance to the idle one would be a lie that looks
            # like data.
            thread = next(
                (t for t in threads if t.mirror_status in ("confirmed", "skipped")),
                threads[0],
            )

            # Walk only as far as the lead's own conversation justifies. A confirmed
            # Problem Mirror is what makes a diagnosis truthful, so a thread that has not
            # confirmed one stops at IN_REVIEW.
            steps = [JourneyEvent.FIRST_TURN.value]
            if thread.mirror_status in ("confirmed", "skipped"):
                steps.append(JourneyEvent.LOOP_CLOSED.value)

            for event in steps:
                if lead.journey_state == JourneyState.DIAGNOSED.value:
                    break
                try:
                    result = advance(lead, event, thread=thread)
                except InvalidTransition:
                    break  # already past this point; nothing to seed
                if result.transition is not None:
                    made += 1

        if made:
            self.stdout.write(
                "  provenance: %s transition(s) recorded with their conversation" % made
            )

    # -- ASTOP (arrived with the 7 Sep backend) --------------------------------
    def _seed_astop(self, leads):
        """
        ASTOP engagements across the GTM v2.3 ch. 2 journey.

        Readiness is deliberately NOT all-green. ``signed_build_availability`` and
        ``deployment_package`` are the two the shipped artefacts genuinely fail - there is
        no Windows build and nothing is signed - so seeding them READY would demo a
        control that is lying. A gate that correctly says "not ready" is the stronger
        thing to show.
        """
        from apps.leads.models import ASTOPEngagement, ASTOPStage

        specs = [
            (0, ASTOPStage.CONTROLLED_EVALUATION, dict(
                agreement="EVAL-2026-0041",
                build="astop-0.4.4-helion-a1",
                attribution="ATTR-HELION-0041",
                readiness={
                    "threat_model": "APPROVED",
                    "data_flow_disclosure": "APPROVED",
                    "retention_policy": "APPROVED",
                    "security_review": "IN_REVIEW",
                    "signed_build_availability": "BLOCKED",
                    "deployment_package": "PENDING",
                },
                measured={"observation_tokens_saved_pct": 31.4, "window_days": 14},
            )),
            (1, ASTOPStage.NDA_BRIEFING, dict(
                agreement="", build="", attribution="",
                readiness={"threat_model": "IN_REVIEW", "retention_policy": "PENDING"},
                measured={},
            )),
            (4, ASTOPStage.IDENTIFY_QUALIFY, dict(
                agreement="", build="", attribution="",
                readiness={"threat_model": "NOT_PROVIDED"},
                measured={},
            )),
        ]

        made = 0
        for idx, stage, extra in specs:
            if idx >= len(leads):
                continue
            lead = leads[idx]
            record, created = ASTOPEngagement.objects.get_or_create(
                lead=lead,
                defaults=dict(
                    stage=stage,
                    evaluation_agreement=extra["agreement"],
                    controlled_build_id=extra["build"],
                    attribution_id=extra["attribution"],
                    qualification_context={
                        "workload": getattr(lead, "workload_type", "") or "unspecified",
                        "observation_cost_material": stage != ASTOPStage.IDENTIFY_QUALIFY,
                    },
                    evaluation_scope=(
                        {"reference_workflow": "agentic-longtask"} if extra["measured"] else {}
                    ),
                    baseline={"window_days": 14, "captured": bool(extra["measured"])},
                    measured_savings=extra["measured"],
                    security_result={"readiness": extra["readiness"]},
                ),
            )
            if created:
                made += 1
            if stage == ASTOPStage.CONTROLLED_EVALUATION and record.authorized_install_at is None:
                record.authorized_install_at = self.now - _d(9)
                record.reproducible_value_at = self.now - _d(7)
                record.save(update_fields=[
                    "authorized_install_at", "reproducible_value_at", "updated_at",
                ])
        self.stdout.write("  ASTOP: %s engagement(s)" % made)

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
