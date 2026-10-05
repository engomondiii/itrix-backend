"""October commercial rules. Provider integrations are deliberately fail-closed.

Only verified provider adapters may call record_payment. No browser-supplied payment
status, redirect or screenshot establishes an entitlement. All state changes are atomic.
"""
import hashlib
import json
import secrets
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string
from .models import (Activation, Branch, CommerceAudit, Delivery, LegalRelease, License,
                     Order, PaymentEvent, Refund, Reward, Seat, VerifiedIdentity, JourneyDecision)

RATES = tuple(map(Decimal, ('0.10', '0.05', '0.025', '0.0125', '0.0075')))


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def audit(action, subject, actor=None, **detail):
    CommerceAudit.objects.create(action=action, subject_id=subject.pk,
        actor_id=getattr(actor, 'pk', None), detail=detail)


def adapter():
    path = getattr(settings, 'ASTOP_COMMERCE_ADAPTER', '')
    require(getattr(settings, 'ASTOP_COMMERCE_ENABLED', False) and path,
            'Commercial delivery is not configured. Contact itriX for access.')
    return import_string(path)()


def active_legal(kind):
    release = LegalRelease.objects.filter(kind=kind, active=True).order_by('-approved_at').first()
    require(release and release.sha256 == digest(release.body), 'Approved agreement unavailable.')
    return release


@transaction.atomic
def publish_legal(*, kind, version, body, actor):
    require(kind in ('lo', 'branch') and body.strip() and version.strip(), 'Invalid agreement.')
    # Final text must be reviewed outside code; the provided Branch draft is not executable.
    require(not any(marker in body.lower() for marker in ('[insert', '[●]', '[to be', 'tbd', '{{', '_____')),
            'Resolve agreement placeholders before approval.')
    LegalRelease.objects.filter(kind=kind, active=True).update(active=False)
    release = LegalRelease.objects.create(kind=kind, version=version, body=body,
        sha256=digest(body), approved_at=timezone.now(), approved_by=actor, active=True)
    audit('legal_published', release, actor, kind=kind, version=version)
    return release


@transaction.atomic
def verify_identity(*, client, kind, details, actor):
    required = ('legal_name', 'country', 'address') if kind == 'individual' else (
        'legal_name', 'country', 'registration_number', 'registered_address',
        'representative_name', 'representative_title', 'authority_basis')
    require(isinstance(details, dict), 'Legal identity fields are required.')
    require(kind in ('individual', 'organization') and client.email_verified_at,
            'Verified email and valid purchaser type are required.')
    require(all(isinstance(details.get(k), str) and details[k].strip() for k in required),
            'Complete verified legal identity is required.')
    identity, _ = VerifiedIdentity.objects.update_or_create(client=client, defaults={
        'kind': kind, 'details': {k: details[k].strip() for k in required},
        'verified_email': client.email.strip().lower(), 'verified_by': actor, 'verified_at': timezone.now()})
    audit('identity_verified', identity, actor, kind=kind)
    return identity


def current_identity(client, kind):
    identity = VerifiedIdentity.objects.filter(client=client, kind=kind).first()
    require(client.is_active and client.email_verified_at and identity and
            identity.verified_email == client.email.strip().lower(), 'Verified purchaser identity and email are required.')
    return identity


@transaction.atomic
def quote(*, client, kind, seats, referral_code=''):
    adapter()  # No order can be offered while integrations are unavailable.
    require(type(seats) is int and ((kind == 'individual' and seats == 1) or
            (kind == 'organization' and 2 <= seats <= 10000)), 'Individual: one seat; organization: 2–10,000 seats.')
    identity = current_identity(client, kind)
    legal = active_legal('lo')
    referral = None
    if referral_code:
        referral = Branch.objects.select_for_update().filter(code=referral_code, status='active').first()
        require(referral and referral.client_id != client.pk, 'Invalid or self-referring Branch code.')
        ref_identity = VerifiedIdentity.objects.filter(client_id=referral.client_id).first()
        if ref_identity and ref_identity.kind == identity.kind:
            keys = ('legal_name', 'country', 'registration_number' if kind == 'organization' else 'address')
            same_party = all(str(ref_identity.details.get(k, '')).strip().casefold() == str(identity.details.get(k, '')).strip().casefold() for k in keys)
            require(not same_party, 'A purchaser cannot refer the same verified legal counterparty.')
    lineage, seen, branch = [], {str(client.pk)}, referral
    while branch and len(lineage) < 5:
        require(str(branch.client_id) not in seen, 'Circular referral is prohibited.')
        require(branch.status == 'active', 'Referral lineage is not eligible.')
        seen.add(str(branch.client_id))
        lineage.append(str(branch.pk))
        branch = branch.parent
    discount = 20 if kind == 'organization' else (10 if referral else 0)
    amount = (Decimal('20.00') * seats * (100 - discount) / 100).quantize(Decimal('.01'))
    snapshot = dict(identity.details, kind=kind, email=identity.verified_email,
                    verification_id=str(identity.pk), verified_at=identity.verified_at.isoformat())
    # Order-specific particulars accompany the exact agreement text and form one evidence blob.
    body = (f'ASTOP License Order\nPurchaser: {snapshot["legal_name"]}\nEmail: {snapshot["email"]}\n'
            f'Legal identity: {json.dumps(identity.details, ensure_ascii=False, sort_keys=True)}\n'
            f'Type: {kind}\nSeats: {seats}\nLicense fee: USD {amount}\nDiscount: {discount}%\n'
            f'Agreement version: {legal.version}\n\n{legal.body}')
    order = Order.objects.create(client=client, kind=kind, seats=seats, amount=amount,
        discount=discount, identity_snapshot=snapshot, legal=legal, legal_body=body,
        legal_hash=digest(body), referral=referral, lineage=lineage)
    audit('order_quoted', order, client)
    return order


@transaction.atomic
def accept_order(*, order_id, client, legal_hash, session):
    order = Order.objects.select_for_update().get(pk=order_id, client=client)
    require(order.status == 'quoted' and order.legal.active, 'Order is no longer available for acceptance.')
    identity = current_identity(client, order.kind)
    require(identity.verified_at.isoformat() == order.identity_snapshot['verified_at'], 'Identity changed; request a new order.')
    require(legal_hash == order.legal_hash and session, 'Accept the exact displayed agreement in an authenticated session.')
    order.accepted_at = timezone.now()
    order.acceptance_session_hash = digest(session)
    order.status = 'accepted'
    order.save()
    audit('order_accepted', order, client)
    return order


@transaction.atomic
def record_payment(*, order_id, provider_id, payment_reference, amount, currency, payload_hash):
    """Trusted adapter only: verified capture, license-fee amount excluding separately charged taxes."""
    order = Order.objects.select_for_update().get(pk=order_id)
    prior = PaymentEvent.objects.filter(provider_id=provider_id).first()
    if prior:
        require(prior.order_id == order.pk and prior.payload_hash == payload_hash and prior.kind == 'capture', 'Conflicting provider event.')
        return order
    require(order.status == 'accepted' and order.accepted_at, 'Payment requires accepted LO.')
    require(Decimal(str(amount)) == order.amount and currency == 'USD' and payment_reference, 'Payment amount or currency mismatch.')
    PaymentEvent.objects.create(provider_id=provider_id, payload_hash=payload_hash, order=order, kind='capture')
    order.status, order.payment_reference, order.paid_at = 'paid', payment_reference, timezone.now()
    order.save()
    license = License.objects.create(order=order)
    if order.kind == 'individual':
        Seat.objects.create(license=license, email=order.identity_snapshot['email'])
    for level, branch_id in enumerate(order.lineage, 1):
        Reward.objects.create(order=order, branch_id=branch_id, level=level, net_base=order.amount,
            amount=order.amount * RATES[level - 1], eligible_at=order.paid_at + timedelta(days=30))
    audit('payment_captured', order)
    return order


@transaction.atomic
def assign_seat(*, license_id, client, email, replace_id=None):
    license = License.objects.select_for_update().select_related('order').get(pk=license_id, order__client=client)
    require(license.status == 'active' and license.order.kind == 'organization', 'Active organization license required.')
    from django.core.validators import validate_email
    email = email.strip().lower()
    validate_email(email)
    if replace_id:
        prior = Seat.objects.get(pk=replace_id, license=license, active=True)
        Activation.objects.filter(seat=prior, revoked_at=None).update(revoked_at=timezone.now())
        prior.active = False
        prior.save()
    require(license.assignments.filter(active=True).count() < license.order.seats, 'Seat limit reached.')
    seat = Seat.objects.create(license=license, email=email)
    audit('seat_assigned', seat, client)
    return seat


def activation_policy():
    policy = {
        'max_environments_per_seat': getattr(settings, 'ASTOP_MAX_ENVIRONMENTS', 3),
        'renewal_days': getattr(settings, 'ASTOP_VALIDATION_DAYS', 7),
        'offline_validity_days': getattr(settings, 'ASTOP_OFFLINE_VALIDITY_DAYS', 14),
        'session_continuity': 'finish_sessions_started_while_entitled',
    }
    # A stale deployment override must not silently change the ordinary offer.
    require((policy['max_environments_per_seat'], policy['renewal_days'],
             policy['offline_validity_days']) == (3, 7, 14),
            'Activation policy configuration requires review: standard policy is 3 environments, 7-day renewal, 14-day offline validity.')
    return policy


@transaction.atomic
def activate(*, license_id, client, environment_hash, replace_id=None, confirm_replacement=False):
    license = License.objects.select_for_update().get(pk=license_id)
    require(license.status == 'active' and client.email_verified_at and client.is_active, 'Active entitlement and verified seat user required.')
    seat = Seat.objects.filter(license=license, email=client.email.strip().lower(), active=True).first()
    require(seat, 'A named seat is required.')
    require(isinstance(environment_hash, str) and len(environment_hash) == 64 and all(c in '0123456789abcdef' for c in environment_hash), 'Hashed environment identifier required.')
    policy = activation_policy()
    now = timezone.now()
    # Expiry does not silently unregister a device; a fourth registration needs replacement.
    registered = Activation.objects.filter(seat=seat, revoked_at=None)
    prior = registered.filter(environment_hash=environment_hash).first()
    if replace_id:
        require(confirm_replacement is True and not prior, 'Explicit confirmation of a new environment replacement is required.')
        replaced = registered.get(pk=replace_id)
        replaced.revoked_at = now
        replaced.save(update_fields=['revoked_at', 'updated_at'])
        audit('environment_replaced', replaced, client)
    else:
        require(not confirm_replacement, 'Select the environment to replace.')
    require(prior or registered.count() < policy['max_environments_per_seat'], 'Three environments are already registered. Confirm which existing environment to replace.')
    activation = prior or Activation(seat=seat, environment_hash=environment_hash)
    activation.token_version = license.token_version
    activation.last_validated_at = now
    activation.renewal_due_at = now + timedelta(days=policy['renewal_days'])
    activation.valid_until = now + timedelta(days=policy['offline_validity_days'])
    activation.save()
    # Only opaque licensing/security data: never workload content. The runtime must
    # gate NEW sessions at expiry and let entitled sessions finish. Revocation stops
    # renewal, not a running job or the previously issued offline validity window.
    token = adapter().sign_activation({'license_id': str(license.pk), 'activation_id': str(activation.pk),
        'environment_hash': environment_hash, 'version': license.token_version,
        'validated_at': now.isoformat(), 'renewal_due_at': activation.renewal_due_at.isoformat(),
        'expires_at': activation.valid_until.isoformat(), 'session_continuity': policy['session_continuity']})
    require(token, 'Activation signer unavailable.')
    audit('activated', activation, client)
    return activation, token


@transaction.atomic
def deliver(*, license_id, client, platform):
    license = License.objects.select_for_update().select_related('order').get(pk=license_id)
    require(client.is_active and client.email_verified_at and (license.order.client_id == client.pk or
            license.assignments.filter(email=client.email.strip().lower(), active=True).exists()),
            'Purchaser or verified named seat user required.')
    require(license.status == 'active', 'An active license is required.')
    require(platform in ('macos-arm64', 'linux-x86_64', 'linux-aarch64'), 'Unsupported platform.')
    artifact = adapter().delivery(license_id=str(license.pk), platform=platform)
    # Adapter must return a short-lived authenticated production-build delivery, never raw debug assets.
    require(all(artifact.get(k) for k in ('build_id', 'sha256', 'signing_identity', 'url')) and
            artifact.get('production') is True and artifact['url'].startswith('https://'), 'Signed production build unavailable.')
    row = Delivery.objects.create(license=license, platform=platform, build_id=artifact['build_id'],
        artifact_sha256=artifact['sha256'], signing_identity=artifact['signing_identity'])
    audit('download_issued', row, client)
    return artifact['url']


@transaction.atomic
def request_refund(*, order_id, client, reason):
    order = Order.objects.select_for_update().get(pk=order_id, client=client)
    require(order.status == 'paid' and order.paid_at and timezone.now() <= order.paid_at + timedelta(days=30),
            'The standard 30-day request window is unavailable. Contact itriX for any mandatory statutory rights.')
    require(bool(reason.strip()), 'Refund reason required.')
    refund, _ = Refund.objects.get_or_create(order=order, defaults={'reason': reason.strip()[:4000]})
    audit('refund_requested', refund, client)
    return refund


@transaction.atomic
def revoke_order(*, order, reason):
    license = License.objects.select_for_update().get(order=order)
    if license.status != 'revoked':
        license.status, license.revoked_at = 'revoked', timezone.now()
        license.token_version += 1
        license.save()
    # Preserve signed offline expiry and job continuity; block future issuance/renewal.
    Activation.objects.filter(seat__license=license, revoked_at=None).update(revoked_at=timezone.now())
    Seat.objects.filter(license=license, active=True).update(active=False)
    Reward.objects.filter(order=order, status='paid').update(status='clawback_due')
    Reward.objects.filter(order=order).exclude(status__in=['clawback_due', 'reversed']).update(status='reversed')
    Branch.objects.filter(qualifying_order=order).update(status='suspended')
    audit('entitlement_revoked', license, reason=reason)


@transaction.atomic
def approve_refund(*, refund_id, actor):
    refund = Refund.objects.select_for_update().get(pk=refund_id)
    order = Order.objects.select_for_update().get(pk=refund.order_id)
    require(refund.status == 'requested' and order.status == 'paid', 'Refund is not awaiting approval.')
    revoke_order(order=order, reason='refund_approved')
    refund.status, refund.approved_at, refund.approved_by = 'repayment_pending', timezone.now(), actor
    refund.save()
    order.status = 'refund_approved'
    order.save()
    audit('refund_approved', refund, actor)
    return refund  # Durable outbox: provider repayment happens AFTER this transaction commits.


def repay_refund(refund_id):
    refund = Refund.objects.select_related('order').get(pk=refund_id, status='repayment_pending')
    # Stable idempotency key: a network timeout cannot cause a second repayment.
    reference = adapter().refund(payment_reference=refund.order.payment_reference,
        amount=str(refund.order.amount), currency='USD', idempotency_key=str(refund.pk))
    require(reference, 'Provider has not confirmed repayment.')
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund_id)
        if refund.status == 'repayment_pending':
            refund.status, refund.provider_reference = 'repaid', reference
            refund.save()
            Order.objects.filter(pk=refund.order_id).update(status='refunded')
            audit('refund_repaid', refund)
    return refund


@transaction.atomic
def apply_branch(*, client, order_id):
    order = Order.objects.select_for_update().get(pk=order_id, client=client, status='paid', license__status='active')
    require(client.email_verified_at, 'Verified email required.')
    branch, _ = Branch.objects.get_or_create(client=client, defaults={'qualifying_order': order})
    audit('branch_applied', branch, client)
    return branch


@transaction.atomic
def approve_branch(*, branch_id, actor):
    branch = Branch.objects.select_for_update().get(pk=branch_id)
    require(branch.status == 'applied' and License.objects.filter(order=branch.qualifying_order, status='active').exists(), 'Eligible licensee application required.')
    release = active_legal('branch')
    branch.status, branch.approved_by, branch.approved_at = 'approved', actor, timezone.now()
    branch.agreement, branch.agreement_body, branch.agreement_hash = release, release.body, release.sha256
    branch.save()
    audit('branch_approved', branch, actor)
    return branch


@transaction.atomic
def accept_branch(*, client, legal_hash, session):
    branch = Branch.objects.select_for_update().select_related('qualifying_order').get(client=client)
    current_identity(client, branch.qualifying_order.kind)
    require(branch.status == 'approved' and branch.agreement.active and legal_hash == branch.agreement_hash and session, 'Accept the approved Branch agreement.')
    require(License.objects.filter(order=branch.qualifying_order, status='active').exists(), 'Active qualifying license required.')
    # Parent derives ONLY from this applicant's earlier qualifying paid purchase.
    branch.parent = branch.qualifying_order.referral
    if branch.parent:
        require(branch.parent.status == 'active' and branch.parent.client_id != client.pk, 'Parent is ineligible.')
    branch.accepted_at, branch.acceptance_session_hash = timezone.now(), digest(session)
    branch.code, branch.status = secrets.token_urlsafe(12), 'active'
    branch.save()
    audit('branch_accepted', branch, client)
    return branch


@transaction.atomic
def release_reward(*, reward_id, actor, settlement_reference, fraud_review_reference):
    reward = Reward.objects.select_for_update().select_related('order', 'branch').get(pk=reward_id)
    require(reward.status == 'pending' and timezone.now() >= reward.eligible_at and
            reward.order.status == 'paid' and reward.branch.status == 'active' and
            License.objects.filter(order=reward.order, status='active').exists() and
            not Refund.objects.filter(order=reward.order).exists() and
            settlement_reference and fraud_review_reference, 'Settlement, refund and fraud clearance required.')
    reward.status = 'eligible'
    reward.save()
    audit('reward_released', reward, actor, settlement=settlement_reference, fraud_review=fraud_review_reference)
    return reward


@transaction.atomic
def record_reversal(*, order_id, provider_id, payload_hash, kind):
    require(kind in ('chargeback', 'refund'), 'Unsupported reversal.')
    order = Order.objects.select_for_update().get(pk=order_id)
    prior = PaymentEvent.objects.filter(provider_id=provider_id).first()
    if prior:
        require(prior.order_id == order.pk and prior.payload_hash == payload_hash and prior.kind == kind, 'Conflicting provider event.')
        return order
    require(order.paid_at, 'Reversal requires a captured payment.')
    PaymentEvent.objects.create(provider_id=provider_id, payload_hash=payload_hash, order=order, kind=kind)
    revoke_order(order=order, reason=kind)
    order.status = 'chargeback' if kind == 'chargeback' else 'refunded'
    order.save()
    audit('payment_reversed', order, kind=kind)
    return order


@transaction.atomic
def review_license(*, license_id, actor, action, review_reference):
    license = License.objects.select_for_update().select_related('order').get(pk=license_id)
    require(review_reference and action in ('suspend', 'restore', 'revoke'), 'Review reference and valid action required.')
    if action == 'revoke':
        revoke_order(order=license.order, reason='operator_review')
    elif action == 'suspend':
        require(license.status == 'active', 'Active license required.')
        license.status = 'suspended'
        license.token_version += 1
        license.save()
        # Preserve signed offline expiry and job continuity; block future issuance/renewal.
        Activation.objects.filter(seat__license=license, revoked_at=None).update(revoked_at=timezone.now())
    else:
        require(license.status == 'suspended' and license.order.status == 'paid', 'Only a paid suspended license can be restored.')
        license.status = 'active'
        license.save()
    audit('license_' + action, license, actor, review=review_reference)
    return license


@transaction.atomic
def record_journey_decision(*, license_id, client, **values):
    license = License.objects.select_for_update().select_related('order').get(pk=license_id)
    require(client.is_active and client.email_verified_at and (license.order.client_id == client.pk or
            license.assignments.filter(email=client.email.strip().lower(), active=True).exists()),
            'Purchaser or verified named seat user required.')
    # Use the same bounded validation for API and service callers.
    from .serializers import JourneyDecisionInput
    data = JourneyDecisionInput(data=values)
    data.is_valid(raise_exception=True)
    values = data.validated_data
    if values['outcome'] in ('continue', 'expand'):
        require(license.status == 'active' and values['comparable'] and
                values['fidelity'] == 'preserved' and values['net_value'] == 'positive' and
                values.get('measured_results', '').strip() and
                Activation.objects.filter(seat__license=license).exists(),
                'Continue or expand requires activation, comparable measured evidence, preserved decisions and positive net value. Otherwise record tune, another workload or stop.')
    decision = JourneyDecision.objects.create(license=license, client=client, **values)
    audit('journey_decision_recorded', decision, client, outcome=decision.outcome,
          license_id=str(license.pk), evidence='customer_reported')
    # This is not a refund request, license change or automatic knowledge ingestion.
    return decision
