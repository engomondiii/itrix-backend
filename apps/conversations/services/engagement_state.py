"""Deterministic Visitor / Customer / consent state (Journey v2.2).

This state is intentionally independent from the numbered progressive-disclosure journey.
It answers *what kind of interaction the person explicitly chose*, not how much content a
subject has earned.  Company, title, seniority, account presence and technical depth are
never promotion inputs.

Visitor -> Customer / Strategic Customer uses the v2.2 four-check gate:
  1. explicit request to assess a concrete workload or organisational decision;
  2. the interface states that it is moving into problem-led assessment;
  3. the person explicitly consents to that mode change;
  4. the same thread/context is preserved.

A qualifying request therefore OFFERS a mode change first.  Relationship state changes
only on a later consent turn.  This makes the gate enforceable on the backend instead of
being a piece of UI theatre.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

REL_VISITOR = "visitor"
REL_TECHNICAL_EVALUATOR = "technical_evaluator"
REL_CUSTOMER = "customer"
REL_STRATEGIC_CUSTOMER = "strategic_customer"

MODE_NONE = "none"
MODE_OFFERED = "offered"
MODE_CONSENTED = "consented"
MODE_DECLINED = "declined"

MIRROR_NOT_REQUIRED = "not_required"
MIRROR_PENDING = "pending"
MIRROR_CONFIRMED = "confirmed"
MIRROR_SKIPPED = "skipped"
MIRROR_REFINE = "refine"
MIRROR_RESTART = "restart"
MIRROR_FALLBACK = "fallback"

CONTRACT_NONE = "no_discussion"
CONTRACT_FRAMEWORK = "framework_discussion"
CONTRACT_TERM_SHEET = "term_sheet"
CONTRACT_DRAFT = "draft"
CONTRACT_EXECUTED = "executed"

IDENTITY_ACTIONS = {
    "nda": "NDA routing",
    "controlled_material": "controlled material access",
    "formal_evaluation": "formal evaluation",
    "human_follow_up": "human follow-up",
    "persistent_workspace": "persistent workspace",
    "licensing": "licensing process",
}

_ORIENTATION = re.compile(
    r"\b(how (?:do|can) i (?:use|interact|navigate)|how (?:does|can) (?:this|the) (?:site|website|platform)|"
    r"what (?:is|does) itrix|tell me (?:about|what) itrix|media|press|research|paper|evidence|"
    r"architecture (?:of|behind) itrix|technical material|documentation)\b",
    re.I,
)
_TECH_EVALUATION = re.compile(
    r"\b(compare|architecture|benchmark|evidence|paper|research|method|axiom|cre|fqnm|"
    r"alpha compute|alpha core|technical|mathematical|runtime|solver|credib|peer review|patent)\b",
    re.I,
)
_EVALUATION_ACTION = re.compile(
    r"\b(evaluate|evaluation|assess|assessment|diagnos(?:e|is)|analyse|analyze|review|test|investigate|"
    r"determine (?:the )?(?:fit|cause)|help (?:us|me) (?:decide|solve|assess|diagnose)|"
    r"solve|find (?:the )?(?:cause|bottleneck)|representation review)\b",
    re.I,
)
_DIRECT_EVALUATION_REQUEST = re.compile(
    r"\b(?:please|can you|could you|would you|i want you to|we want you to|we need you to|help (?:us|me) to?)\s+"
    r"(?:evaluate|assess|diagnose|analyse|analyze|review|test|investigate)\b|"
    r"\b(?:evaluate|assess|diagnose|analyse|analyze|review|test|investigate)\s+(?:our|my|this|the)\b",
    re.I,
)
# Questions about what a future/non-confidential intake *would* require are still public
# technical evaluation.  They are not requests to begin evaluating a workload now.  This
# protects the v2.2 explicit-consent boundary without keying on any company or test prompt.
_FUTURE_EVALUATION_INTAKE = re.compile(
    r"\b(?:suppose|hypothetical(?:ly)?|tomorrow|before i (?:disclose|share|provide)|"
    r"what information (?:can|could|should|would) i provide|minimum input(?: set)?|"
    r"what (?:do|would) you need (?:before|to decide)|"
    r"whether.{0,80}evaluation.{0,40}worth(?:while| doing)?)\b",
    re.I | re.S,
)
_WORKLOAD = re.compile(
    r"\b(our|my|we|i)\b.{0,140}\b(workload|pipeline|model|inference|training|solver|simulation|"
    r"compute|gpu|npu|accelerator|runtime|latency|memory|bandwidth|battery|thermal|power|"
    r"cost|throughput|agentic|kernel|operator|spatial|perception|rendering|fleet|cluster|system)\b|"
    r"\b(workload|pipeline|model|solver|inference|training|system)\b.{0,140}\b(our|my|we)\b",
    re.I | re.S,
)
_STRATEGIC = re.compile(
    r"\b(adopt|adoption|rollout|roadmap|platform strategy|architecture decision|decision|"
    r"standardize|standardise|capacity plan|fleet strategy|product strategy|business case|stakeholder|"
    r"internal alignment|across (?:our|the) (?:platform|fleet|organization|organisation|product|devices)|"
    r"make a case|recommendation to|board|executive team|multi[- ]year|commitment)\b",
    re.I,
)

_MODE_ACCEPT = re.compile(
    r"^\s*(yes|yes[, ]+proceed|proceed|continue|enter (?:the )?assessment|start (?:the )?assessment|"
    r"move (?:me|us) into (?:the )?assessment|i consent|we consent|do it|let'?s proceed)\s*[.!]?\s*$",
    re.I,
)
_MODE_DECLINE = re.compile(
    r"^\s*(no|not now|stay (?:a )?visitor|stay in (?:technical )?evaluation|continue (?:publicly|anonymously)|"
    r"do not enter (?:the )?assessment|keep this informational)\s*[.!]?\s*$",
    re.I,
)

_CONTROLLED_EVAL = re.compile(
    r"\b(start|begin|proceed with|set up|scope|run|choose|select|want|would like)\b.{0,60}"
    r"\b(controlled (?:technical )?evaluation|formal evaluation|bounded evaluation|assessment)\b",
    re.I | re.S,
)
_POC = re.compile(
    r"\b(start|begin|proceed with|set up|scope|run|choose|select|want|would like)\b.{0,40}"
    r"\b(poc|proof[- ]of[- ]concept)\b",
    re.I | re.S,
)
_NDA = re.compile(
    r"\b(start|sign|request|arrange|proceed with|need|want|would like)\b.{0,30}\bnda\b|"
    r"\bnda\b.{0,30}\b(start|sign|request|arrange|proceed|need|want)\b",
    re.I | re.S,
)
_LICENSING = re.compile(
    r"\b(start|begin|negotiate|scope|discuss|enter|want|would like)\b.{0,50}"
    r"\b(licen[cs](?:e|ing)|commercial agreement|term sheet)\b",
    re.I | re.S,
)
_WORKSPACE = re.compile(
    r"\b(create|open|keep|save|persist)\b.{0,30}\b(workspace|conversation|review|brief)\b",
    re.I | re.S,
)
_HUMAN = re.compile(
    r"\b(speak|talk|meet|call|connect|follow up)\b.{0,35}\b(team|person|engineer|specialist|human|itrix)\b",
    re.I | re.S,
)
_CONTROLLED_MATERIAL = re.compile(
    r"\b(access|see|show|send|share)\b.{0,40}\b(controlled|restricted|nda[- ]only|confidential)\b.{0,30}\b(material|document|detail|information|content)\b",
    re.I | re.S,
)
_DECLINE_IDENTITY = re.compile(
    r"\b(no email|don't (?:want to )?share (?:my )?email|do not (?:ask|need) (?:for )?(?:my )?email|"
    r"continue anonymously|stay anonymous|not now|skip (?:the )?(?:email|signup|workspace)|"
    r"without (?:an )?email|rather not share)\b",
    re.I,
)

_CONFIRM_MIRROR = re.compile(r"^\s*(this reflects my situation|that reflects my situation|confirmed|yes,? that(?:'s| is) right|제 상황을 잘 반영합니다|이 내용이 제 상황과 맞습니다|맞습니다)\s*[.!]?\s*$", re.I)
_REFINE_MIRROR = re.compile(r"^\s*(refine this|refine the mirror|that's not quite right|that is not quite right|수정해 주세요|이 내용을 수정해 주세요|조정해 주세요)\b", re.I)
_RESTART_MIRROR = re.compile(r"^\s*(start again|restart|reset the mirror|처음부터 다시|다시 시작|처음부터 다시 시작)\s*[.!]?\s*$", re.I)
_SKIP_MIRROR = re.compile(r"^\s*(skip (?:the )?(?:mirror|reflection)|skip and continue|continue without (?:the )?(?:mirror|reflection)|미러 건너뛰기|확인 없이 계속)\s*[.!]?\s*$", re.I)
_KOREAN = re.compile(r"[\uac00-\ud7af]")


@dataclass(frozen=True)
class Decision:
    relationship: str
    customer_started: bool = False
    mirror_action: str = ""
    selected_action: str = ""
    identity_needed_action: str = ""
    cta_declined: bool = False
    locale: str = "en"
    mode_change_offered: bool = False
    mode_change_accepted: bool = False
    mode_change_declined: bool = False


def _append_consent(thread, event: str, *, detail: str = "") -> None:
    history = list(getattr(thread, "consent_history", None) or [])
    history.append({"event": event, "detail": detail})
    thread.consent_history = history[-50:]


def _save(thread, fields: Iterable[str]) -> None:
    thread.save(update_fields=list(dict.fromkeys([*fields, "updated_at"])))


def mode_change_offer_text(thread) -> str:
    """Visitor-facing statement required by v2.2 check 2, with context-preservation explicit."""
    target = getattr(thread, "mode_change_target", "") or REL_CUSTOMER
    locale = (getattr(thread, "locale", "en") or "en").lower()
    if locale.startswith("ko"):
        if target == REL_STRATEGIC_CUSTOMER:
            what = "방금 설명하신 조직 의사결정을 중심으로 한 전략적 평가"
        else:
            what = "방금 설명하신 워크로드 또는 운영 문제를 중심으로 한 평가"
        return (
            f"지금 요청은 공개 탐색에서 {what}로 전환하는 것입니다. "
            "평가를 시작하면 먼저 6개 항목의 Problem Mirror를 제시하며, 이를 확인하거나 명시적으로 건너뛰기 전에는 "
            "제품 경로나 다음 단계를 추천하지 않습니다. 기존 대화, 수정 내용, 자료와 접근 상태는 그대로 유지됩니다. "
            "이 평가 모드로 전환할까요?"
        )
    if target == REL_STRATEGIC_CUSTOMER:
        what = "a decision-led strategic assessment of the organisational decision you described"
    else:
        what = "a problem-led assessment of the workload or operational problem you described"
    return (
        f"You’re asking itriX to move from public exploration into {what}. "
        "If you enter that assessment, I’ll build a six-part Problem Mirror first; no product route "
        "will be recommended until you confirm or deliberately skip that reflection. Your existing "
        "conversation, corrections, resources and access state stay with you. Would you like to enter that assessment?"
    )


def update_from_turn(thread, body: str) -> Decision:
    text = (body or "").strip()
    if thread is None:
        return Decision(relationship=REL_VISITOR)

    dirty: list[str] = []
    locale = "ko" if _KOREAN.search(text) else (getattr(thread, "locale", "") or "en")
    if locale != getattr(thread, "locale", "en"):
        thread.locale = locale
        dirty.append("locale")

    if _DECLINE_IDENTITY.search(text):
        thread.cta_declined = True
        thread.identity_needed_action = ""
        dirty.extend(["cta_declined", "identity_needed_action"])
        _append_consent(thread, "identity_declined")
        dirty.append("consent_history")

    mirror_action = ""
    if _CONFIRM_MIRROR.match(text):
        thread.mirror_status = MIRROR_CONFIRMED
        mirror_action = "confirm"
        _append_consent(thread, "problem_mirror_confirmed")
        dirty.extend(["mirror_status", "consent_history"])
    elif _REFINE_MIRROR.match(text):
        thread.mirror_status = MIRROR_REFINE
        mirror_action = "refine"
        _append_consent(thread, "problem_mirror_refine_requested")
        dirty.extend(["mirror_status", "consent_history"])
    elif _RESTART_MIRROR.match(text):
        thread.mirror_status = MIRROR_RESTART
        mirror_action = "restart"
        _append_consent(thread, "problem_mirror_restart_requested")
        dirty.extend(["mirror_status", "consent_history"])
    elif _SKIP_MIRROR.match(text):
        thread.mirror_status = MIRROR_SKIPPED
        mirror_action = "skip"
        _append_consent(thread, "problem_mirror_deliberately_skipped")
        dirty.extend(["mirror_status", "consent_history"])

    old_relationship = getattr(thread, "relationship_state", REL_VISITOR) or REL_VISITOR
    relationship = old_relationship
    mode_change_offered = False
    mode_change_accepted = False
    mode_change_declined = False

    # Checks 2 + 3: a pending offer can only be accepted by an explicit consent turn.
    if getattr(thread, "mode_change_status", MODE_NONE) == MODE_OFFERED:
        if _MODE_ACCEPT.match(text):
            target = getattr(thread, "mode_change_target", "") or REL_CUSTOMER
            relationship = target if target in (REL_CUSTOMER, REL_STRATEGIC_CUSTOMER) else REL_CUSTOMER
            thread.mode_change_status = MODE_CONSENTED
            thread.mode_change_target = relationship
            thread.relationship_state = relationship
            thread.mirror_status = MIRROR_PENDING
            dirty.extend(["mode_change_status", "mode_change_target", "relationship_state", "mirror_status"])
            _append_consent(thread, "assessment_mode_consented", detail=relationship)
            _append_consent(thread, "relationship_transition", detail=f"{old_relationship}->{relationship}")
            dirty.append("consent_history")
            mode_change_accepted = True
        elif _MODE_DECLINE.match(text):
            thread.mode_change_status = MODE_DECLINED
            thread.mode_change_target = ""
            dirty.extend(["mode_change_status", "mode_change_target"])
            _append_consent(thread, "assessment_mode_declined")
            dirty.append("consent_history")
            mode_change_declined = True

    # Check 1. A qualifying request creates an OFFER only. Technical scrutiny and general
    # purpose questions stay Visitor/Technical Evaluator. Seniority/company never enter.
    if relationship in (REL_VISITOR, REL_TECHNICAL_EVALUATOR) and not mode_change_accepted:
        # A future/intake question can mention a real workload and the word "evaluation"
        # without asking itriX to start one.  Direct requests/commitments still win; purely
        # hypothetical or minimum-input questions remain in Visitor/Technical Evaluator mode.
        informational_intake = bool(
            _FUTURE_EVALUATION_INTAKE.search(text)
            and not _CONTROLLED_EVAL.search(text)
            and not _DIRECT_EVALUATION_REQUEST.search(text)
        )
        concrete_eval = bool(
            _WORKLOAD.search(text)
            and _EVALUATION_ACTION.search(text)
            and not informational_intake
        )
        if concrete_eval:
            target = REL_STRATEGIC_CUSTOMER if _STRATEGIC.search(text) else REL_CUSTOMER
            if getattr(thread, "mode_change_status", MODE_NONE) != MODE_OFFERED:
                thread.mode_change_target = target
                thread.mode_change_status = MODE_OFFERED
                dirty.extend(["mode_change_target", "mode_change_status"])
                _append_consent(thread, "assessment_mode_offered", detail=target)
                dirty.append("consent_history")
                mode_change_offered = True
        elif _ORIENTATION.search(text):
            relationship = REL_VISITOR
            if relationship != old_relationship:
                thread.relationship_state = relationship
                dirty.append("relationship_state")
        elif _TECH_EVALUATION.search(text):
            relationship = REL_TECHNICAL_EVALUATOR
            if relationship != old_relationship:
                thread.relationship_state = relationship
                dirty.append("relationship_state")

    # Once in Customer mode, strategic promotion also needs a separately stated/consented
    # mode change. Do not infer it from a strategic word inside an ordinary customer turn.
    if old_relationship == REL_CUSTOMER and relationship == REL_CUSTOMER and _STRATEGIC.search(text) and _EVALUATION_ACTION.search(text):
        if getattr(thread, "mode_change_status", MODE_NONE) != MODE_OFFERED:
            thread.mode_change_target = REL_STRATEGIC_CUSTOMER
            thread.mode_change_status = MODE_OFFERED
            dirty.extend(["mode_change_target", "mode_change_status"])
            _append_consent(thread, "assessment_mode_offered", detail=REL_STRATEGIC_CUSTOMER)
            dirty.append("consent_history")
            mode_change_offered = True

    customer_started = mode_change_accepted and relationship in (REL_CUSTOMER, REL_STRATEGIC_CUSTOMER)

    selected_action = ""
    identity_action = ""
    stage_label = ""
    evaluation_type = ""
    if _CONTROLLED_EVAL.search(text):
        selected_action, identity_action = "start_controlled_evaluation", "formal_evaluation"
        stage_label, evaluation_type = "Controlled evaluation", "controlled_evaluation"
    elif _POC.search(text):
        selected_action, identity_action = "start_poc", "formal_evaluation"
        stage_label, evaluation_type = "PoC", "poc"
    elif _NDA.search(text):
        selected_action, identity_action, stage_label = "start_nda", "nda", "NDA"
    elif _LICENSING.search(text):
        selected_action, identity_action, stage_label = "start_licensing", "licensing", "Licensing discussion"
    elif _CONTROLLED_MATERIAL.search(text):
        selected_action, identity_action = "request_controlled_material", "controlled_material"
    elif _HUMAN.search(text):
        selected_action, identity_action = "human_follow_up", "human_follow_up"
    elif _WORKSPACE.search(text):
        selected_action, identity_action = "persistent_workspace", "persistent_workspace"

    # Action selection is recorded even in Visitor mode, but it cannot itself promote the
    # relationship or bypass mirror/identity gates downstream.
    if selected_action:
        thread.selected_action = selected_action
        thread.identity_needed_action = identity_action
        thread.cta_declined = False
        dirty.extend(["selected_action", "identity_needed_action", "cta_declined"])
        if stage_label:
            thread.selected_stage_label = stage_label
            thread.engagement_stage = evaluation_type or selected_action
            dirty.extend(["selected_stage_label", "engagement_stage"])
        if evaluation_type:
            thread.evaluation_type = evaluation_type
            dirty.append("evaluation_type")
        _append_consent(thread, "action_selected", detail=selected_action)
        dirty.append("consent_history")

    # Contract state is evidence-driven. Merely asking what licensing, ownership or a
    # term means is not a contract-state event. An explicit request to *start a licensing
    # discussion* can enter framework discussion; draft/term-sheet/executed states are
    # synchronized only from durable legal/commercial records elsewhere.
    if selected_action == "start_licensing" and getattr(thread, "contract_stage", CONTRACT_NONE) == CONTRACT_NONE:
        thread.contract_stage = CONTRACT_FRAMEWORK
        dirty.append("contract_stage")

    if dirty:
        _save(thread, dirty)

    return Decision(
        relationship=relationship,
        customer_started=customer_started,
        mirror_action=mirror_action,
        selected_action=selected_action,
        identity_needed_action=identity_action,
        cta_declined=bool(getattr(thread, "cta_declined", False)),
        locale=locale,
        mode_change_offered=mode_change_offered,
        mode_change_accepted=mode_change_accepted,
        mode_change_declined=mode_change_declined,
    )


def is_customer(thread) -> bool:
    return getattr(thread, "relationship_state", REL_VISITOR) in (REL_CUSTOMER, REL_STRATEGIC_CUSTOMER)


def recommendation_allowed(thread) -> bool:
    if not is_customer(thread):
        return False
    return getattr(thread, "mirror_status", MIRROR_NOT_REQUIRED) in (MIRROR_CONFIRMED, MIRROR_SKIPPED)


def identity_action_selected(thread) -> bool:
    return bool(getattr(thread, "identity_needed_action", "")) and not bool(getattr(thread, "cta_declined", False))


def public_state(thread) -> dict:
    return {
        "relationshipState": getattr(thread, "relationship_state", REL_VISITOR),
        "engagementStage": getattr(thread, "engagement_stage", "exploration"),
        "selectedStageLabel": getattr(thread, "selected_stage_label", ""),
        "selectedAction": getattr(thread, "selected_action", ""),
        "modeChangeStatus": getattr(thread, "mode_change_status", MODE_NONE),
        "modeChangeTarget": getattr(thread, "mode_change_target", ""),
        "mirrorStatus": getattr(thread, "mirror_status", MIRROR_NOT_REQUIRED),
        "identityNeededAction": getattr(thread, "identity_needed_action", ""),
        "ctaDeclined": bool(getattr(thread, "cta_declined", False)),
        "evaluationType": getattr(thread, "evaluation_type", ""),
        "contractStage": getattr(thread, "contract_stage", CONTRACT_NONE),
        "locale": getattr(thread, "locale", "en") or "en",
        "recommendationAllowed": recommendation_allowed(thread),
    }
