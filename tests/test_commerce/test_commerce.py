from datetime import timedelta
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.commerce import services as s
from apps.commerce.models import (Activation, Branch, LegalRelease, License, Order, PaymentEvent, Refund, Reward, Seat)
from tests.factories.client_factory import ClientFactory
from tests.factories.user_factory import AdminUserFactory

pytestmark = pytest.mark.django_db

class Adapter:
    def sign_activation(self, claims):
        assert 'email' not in claims
        return 'signed-opaque-test-token'
    def delivery(self, **kwargs):
        return {'production': True, 'build_id': 'test-build', 'sha256': 'b'*64, 'signing_identity': 'test-signer', 'url': 'https://example.test/artifact'}
    def refund(self, **kwargs):
        return 'confirmed-refund'

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(s, 'adapter', lambda: Adapter())
    actor = AdminUserFactory()
    s.publish_legal(kind='lo', version='2.6-test', body='Approved test LO terms.', actor=actor)
    s.publish_legal(kind='branch', version='1.4-test', body='Approved test Branch terms.', actor=actor)
    return actor

def buyer(actor, kind='individual'):
    client = ClientFactory(email_verified_at=timezone.now())
    details = {'legal_name': str(client.pk), 'country': 'KE', 'address': 'Test address',
        'registration_number': 'TEST-1', 'registered_address': 'Test address', 'representative_name': 'Test Person',
        'representative_title': 'Director', 'authority_basis': 'Verified test evidence'}
    s.verify_identity(client=client, kind=kind, details=details, actor=actor)
    return client

def purchase(actor, kind='individual', seats=1, code=''):
    client = buyer(actor, kind)
    order = s.quote(client=client, kind=kind, seats=seats, referral_code=code)
    s.accept_order(order_id=order.pk, client=client, legal_hash=order.legal_hash, session='test-session')
    s.record_payment(order_id=order.pk, provider_id=str(order.pk), payment_reference=str(order.pk), amount=order.amount, currency='USD', payload_hash='a'*64)
    order.refresh_from_db()
    return client, order

def branch_for(actor, client, order):
    b=s.apply_branch(client=client, order_id=order.pk)
    s.approve_branch(branch_id=b.pk, actor=actor)
    b.refresh_from_db()
    return s.accept_branch(client=client, legal_hash=b.agreement_hash, session='session')

def test_default_checkout_disabled(settings):
    settings.ASTOP_COMMERCE_ENABLED=False
    with pytest.raises(ValidationError): s.adapter()

def test_claimed_identity_and_email_are_not_verification(setup):
    client=ClientFactory(email_verified_at=timezone.now(), identity_verified_at=timezone.now())
    with pytest.raises(ValidationError): s.quote(client=client,kind='individual',seats=1)

def test_identity_email_change_invalidates_quote(setup):
    c=buyer(setup); c.email='changed@example.test';c.save()
    with pytest.raises(ValidationError): s.quote(client=c,kind='individual',seats=1)

def test_organization_min_seats_and_nonstacking_attribution(setup):
    c,o=purchase(setup);b=branch_for(setup,c,o)
    org=buyer(setup,'organization')
    with pytest.raises(ValidationError):s.quote(client=org,kind='organization',seats=1)
    quote=s.quote(client=org,kind='organization',seats=2,referral_code=b.code)
    assert quote.amount==Decimal('32.00') and quote.discount==20 and quote.referral==b
    solo=buyer(setup)
    assert s.quote(client=solo,kind='individual',seats=1,referral_code=b.code).amount==Decimal('18.00')
    with pytest.raises(ValidationError):s.quote(client=c,kind='individual',seats=1,referral_code=b.code)

def test_exact_agreement_and_no_license_before_payment(setup):
    c=buyer(setup);o=s.quote(client=c,kind='individual',seats=1)
    with pytest.raises(ValidationError):s.accept_order(order_id=o.pk,client=c,legal_hash='stale',session='x')
    with pytest.raises(ValidationError):s.record_payment(order_id=o.pk,provider_id='x',payment_reference='x',amount=20,currency='USD',payload_hash='x')
    s.accept_order(order_id=o.pk,client=c,legal_hash=o.legal_hash,session='x')
    assert not License.objects.exists()
    with pytest.raises(ValidationError):s.record_payment(order_id=o.pk,provider_id='x',payment_reference='x',amount=19,currency='USD',payload_hash='x')
    assert not PaymentEvent.objects.exists()

def test_duplicate_capture_is_idempotent_and_conflicts_rejected(setup):
    c,o=purchase(setup)
    s.record_payment(order_id=o.pk,provider_id=str(o.pk),payment_reference=str(o.pk),amount=20,currency='USD',payload_hash='a'*64)
    assert License.objects.count()==1 and PaymentEvent.objects.count()==1
    with pytest.raises(ValidationError):s.record_payment(order_id=o.pk,provider_id=str(o.pk),payment_reference=str(o.pk),amount=20,currency='USD',payload_hash='changed')

def test_seat_limits_and_reassignment_revoke_old_activations(setup):
    c,o=purchase(setup,'organization',2)
    l=License.objects.get(order=o)
    seat=s.assign_seat(license_id=l.pk,client=c,email=c.email)
    s.activate(license_id=l.pk,client=c,environment_hash='a'*64)
    s.assign_seat(license_id=l.pk,client=c,email='second@example.test')
    with pytest.raises(ValidationError):s.assign_seat(license_id=l.pk,client=c,email='third@example.test')
    s.assign_seat(license_id=l.pk,client=c,email='replacement@example.test',replace_id=seat.pk)
    assert Activation.objects.get(seat=seat).revoked_at
    with pytest.raises(ValidationError):s.activate(license_id=l.pk,client=c,environment_hash='a'*64)

def test_refund_revokes_before_failed_repayment_and_retry(setup,monkeypatch):
    c,o=purchase(setup);l=License.objects.get(order=o)
    s.activate(license_id=l.pk,client=c,environment_hash='c'*64)
    r=s.request_refund(order_id=o.pk,client=c,reason='Not suitable')
    s.approve_refund(refund_id=r.pk,actor=setup)
    l.refresh_from_db();assert l.status=='revoked' and l.token_version==1
    with pytest.raises(ValidationError):s.deliver(license_id=l.pk,client=c,platform='macos-arm64')
    with pytest.raises(ValidationError):s.activate(license_id=l.pk,client=c,environment_hash='c'*64)
    monkeypatch.setattr(Adapter,'refund',lambda self,**kw: None)
    with pytest.raises(ValidationError):s.repay_refund(r.pk)
    r.refresh_from_db();assert r.status=='repayment_pending'
    monkeypatch.setattr(Adapter,'refund',lambda self,**kw: 'settled')
    assert s.repay_refund(r.pk).status=='repaid'

def test_branch_parent_only_from_prior_purchase_and_five_level_rewards(setup):
    c,o=purchase(setup);b=branch_for(setup,c,o)
    assert b.parent is None
    for _ in range(6):
        c,o=purchase(setup,code=b.code);b=branch_for(setup,c,o)
    rewards=list(Reward.objects.filter(order=o).order_by('level'))
    assert len(rewards)==5
    assert sum(r.amount for r in rewards)==Decimal('3.5100')
    assert all(r.status=='pending' for r in rewards)
    with pytest.raises(ValidationError):s.release_reward(reward_id=rewards[0].pk,actor=setup,settlement_reference='x',fraud_review_reference='y')
    s.record_reversal(order_id=o.pk,provider_id='chargeback',payload_hash='hash',kind='chargeback')
    assert set(Reward.objects.filter(order=o).values_list('status',flat=True))=={'reversed'}
    b.refresh_from_db();assert b.status=='suspended'

def test_branch_requires_separate_approval_then_acceptance(setup):
    c,o=purchase(setup);b=s.apply_branch(client=c,order_id=o.pk)
    assert b.code is None
    with pytest.raises(ValidationError):s.accept_branch(client=c,legal_hash='anything',session='x')
    s.approve_branch(branch_id=b.pk,actor=setup);b.refresh_from_db()
    assert b.code is None
    s.accept_branch(client=c,legal_hash=b.agreement_hash,session='x')
    b.refresh_from_db();assert b.code

def test_legal_placeholders_block_publication(setup):
    with pytest.raises(ValidationError):s.publish_legal(kind='branch',version='draft',body='Payee [insert name]',actor=setup)

def test_client_cannot_access_operations_or_another_order(setup,api_client):
    c,o=purchase(setup);other=buyer(setup)
    api_client.force_authenticate(user=other)
    response=api_client.get('/api/v1/commerce/operations/')
    assert response.status_code==403
    response=api_client.post(f'/api/v1/commerce/orders/{o.pk}/refund/',{'reason':'x'})
    assert response.status_code==409

def test_no_anonymous_purchase_or_forged_browser_payment(api_client):
    assert api_client.post('/api/v1/commerce/orders/',{}).status_code in (401,403)
    response=api_client.post('/api/v1/commerce/provider-events/',{'verified':True,'kind':'capture'})
    assert response.status_code==400


def test_published_legal_body_cannot_be_edited(setup):
    release=LegalRelease.objects.get(kind='lo')
    release.body='Changed after publication'
    with pytest.raises(ValidationError):release.save()


def test_suspension_blocks_delivery_and_activation_then_restores(setup):
    c,o=purchase(setup);l=License.objects.get(order=o)
    s.activate(license_id=l.pk,client=c,environment_hash='d'*64)
    s.review_license(license_id=l.pk,actor=setup,action='suspend',review_reference='review-1')
    with pytest.raises(ValidationError):s.deliver(license_id=l.pk,client=c,platform='macos-arm64')
    with pytest.raises(ValidationError):s.activate(license_id=l.pk,client=c,environment_hash='d'*64)
    s.review_license(license_id=l.pk,actor=setup,action='restore',review_reference='review-2')
    assert s.deliver(license_id=l.pk,client=c,platform='macos-arm64').startswith('https:')


def test_activation_windows_replacement_and_signed_continuity(setup, monkeypatch):
    c, o = purchase(setup)
    license = License.objects.get(order=o)
    captured = []
    monkeypatch.setattr(Adapter, 'sign_activation', lambda self, claims: captured.append(claims) or 'signed')
    first, _ = s.activate(license_id=license.pk, client=c, environment_hash='a'*64)
    assert first.renewal_due_at - first.last_validated_at == timedelta(days=7)
    assert first.valid_until - first.last_validated_at == timedelta(days=14)
    assert captured[-1]['session_continuity'] == 'finish_sessions_started_while_entitled'
    assert set(captured[-1]) == {'license_id', 'activation_id', 'environment_hash', 'version',
                               'validated_at', 'renewal_due_at', 'expires_at', 'session_continuity'}
    for char in 'bc':
        s.activate(license_id=license.pk, client=c, environment_hash=char*64)
    with pytest.raises(ValidationError):
        s.activate(license_id=license.pk, client=c, environment_hash='d'*64)
    with pytest.raises(ValidationError):
        s.activate(license_id=license.pk, client=c, environment_hash='d'*64, replace_id=first.pk)
    # Renewal consumes no additional environment.
    s.activate(license_id=license.pk, client=c, environment_hash='b'*64)
    replacement, _ = s.activate(license_id=license.pk, client=c, environment_hash='d'*64,
                              replace_id=first.pk, confirm_replacement=True)
    first.refresh_from_db()
    assert first.revoked_at and replacement.pk != first.pk
    assert Activation.objects.filter(revoked_at=None).count() == 3


def test_replacement_cannot_take_another_seat_and_signer_failure_rolls_back(setup, monkeypatch):
    from django.core.exceptions import ObjectDoesNotExist
    c, o = purchase(setup)
    other, other_order = purchase(setup)
    foreign, _ = s.activate(license_id=other_order.license.pk, client=other, environment_hash='a'*64)
    with pytest.raises(ObjectDoesNotExist):
        s.activate(license_id=o.license.pk, client=c, environment_hash='b'*64,
                   replace_id=foreign.pk, confirm_replacement=True)
    own, _ = s.activate(license_id=o.license.pk, client=c, environment_hash='c'*64)
    monkeypatch.setattr(Adapter, 'sign_activation', lambda self, claims: None)
    with pytest.raises(ValidationError):
        s.activate(license_id=o.license.pk, client=c, environment_hash='d'*64,
                   replace_id=own.pk, confirm_replacement=True)
    own.refresh_from_db()
    assert own.revoked_at is None
    assert Activation.objects.filter(seat=own.seat).count() == 1


def test_refund_preserves_existing_offline_expiry_but_blocks_renewal(setup):
    c, o = purchase(setup)
    activation, _ = s.activate(license_id=o.license.pk, client=c, environment_hash='e'*64)
    expires = activation.valid_until
    refund = s.request_refund(order_id=o.pk, client=c, reason='No fit')
    s.approve_refund(refund_id=refund.pk, actor=setup)
    activation.refresh_from_db()
    assert activation.valid_until == expires and activation.revoked_at
    with pytest.raises(ValidationError):
        s.activate(license_id=o.license.pk, client=c, environment_hash='e'*64)


def test_activation_api_rejects_workload_and_bad_replacement_identifier(setup, api_client):
    c, o = purchase(setup)
    api_client.force_authenticate(user=c)
    url = f'/api/v1/commerce/licenses/{o.license.pk}/activate/'
    for extra in ({'workload': 'private prompt'}, {'replace_id': 'bad'}):
        assert api_client.post(url, {'environment_hash': 'a'*64, **extra}, format='json').status_code == 400
    assert not Activation.objects.exists()


def test_named_seat_can_find_license_without_seeing_peer_emails(setup, api_client):
    owner, order = purchase(setup, 'organization', 2)
    member = buyer(setup)
    s.assign_seat(license_id=order.license.pk, client=owner, email=member.email)
    s.assign_seat(license_id=order.license.pk, client=owner, email=owner.email)
    api_client.force_authenticate(user=member)
    rows = api_client.get('/api/v1/commerce/licenses/').json()
    assert len(rows) == 1 and rows[0]['is_administrator'] is False
    assert [r['email'] for r in rows[0]['assignments']] == [member.email.lower()]
    assert s.deliver(license_id=order.license.pk, client=member, platform='macos-arm64')
    with pytest.raises(License.DoesNotExist):
        s.assign_seat(license_id=order.license.pk, client=member, email='outsider@example.test')


def test_stale_activation_configuration_fails_closed(setup, settings):
    c, o = purchase(setup)
    settings.ASTOP_MAX_ENVIRONMENTS = 2
    with pytest.raises(ValidationError, match='configuration requires review'):
        s.activate(license_id=o.license.pk, client=c, environment_hash='a'*64)
    assert not Activation.objects.exists()


def test_decision_outcomes_are_private_reported_feedback_not_refunds_or_knowledge(setup, api_client):
    from apps.commerce.models import JourneyDecision
    from apps.knowledge_core.models import KnowledgeDocument
    c, order = purchase(setup)
    other = buyer(setup)
    url = f'/api/v1/commerce/licenses/{order.license.pk}/decisions/'
    payload = {'outcome': 'refund', 'workload': 'Approved workload label', 'comparable': False,
               'fidelity': 'unknown', 'net_value': 'unknown', 'measured_results': '',
               'qualitative_feedback': 'Not suitable; approved summary only.'}
    documents_before = KnowledgeDocument.objects.count()
    api_client.force_authenticate(user=other)
    assert api_client.post(url, payload, format='json').status_code == 400
    api_client.force_authenticate(user=c)
    response = api_client.post(url, payload, format='json')
    assert response.status_code == 201
    assert response.json()['evidence_status'] == 'customer_reported'
    assert response.json()['measured_results'] == ''
    assert len(api_client.get(url).json()) == 1
    assert not Refund.objects.filter(order=order).exists()
    assert KnowledgeDocument.objects.count() == documents_before
    assert order.license.status == 'active'
    api_client.force_authenticate(user=other)
    assert api_client.get(url).json() == []
    assert JourneyDecision.objects.count() == 1


def test_continue_and_expand_need_activation_and_comparable_positive_proof(setup):
    c, order = purchase(setup)
    values = {'outcome': 'continue', 'workload': 'Task A', 'comparable': True,
              'fidelity': 'preserved', 'net_value': 'positive',
              'measured_results': 'Baseline 100 calls; ASTOP 60 under equivalent conditions.',
              'qualitative_feedback': 'No required decisions missed; observer cost included.'}
    with pytest.raises(ValidationError):
        s.record_journey_decision(license_id=order.license.pk, client=c, **values)
    s.activate(license_id=order.license.pk, client=c, environment_hash='f'*64)
    for change in ({'comparable': False}, {'fidelity': 'failed'}, {'net_value': 'unknown'}, {'measured_results': ''}):
        with pytest.raises(ValidationError):
            s.record_journey_decision(license_id=order.license.pk, client=c, **{**values, **change})
    for outcome in ('continue', 'expand'):
        row = s.record_journey_decision(license_id=order.license.pk, client=c, **{**values, 'outcome': outcome})
        assert row.outcome == outcome


def test_decision_schema_rejects_unbounded_or_forged_fields(setup, api_client):
    c, order = purchase(setup)
    api_client.force_authenticate(user=c)
    url = f'/api/v1/commerce/licenses/{order.license.pk}/decisions/'
    payload = {'outcome': 'stop', 'workload': 'Task', 'fidelity': 'unknown',
               'net_value': 'unknown', 'qualitative_feedback': 'No fit.'}
    for change in ({'verified': True}, {'outcome': 'approved'}, {'qualitative_feedback': 'x'*4001}):
        assert api_client.post(url, {**payload, **change}, format='json').status_code == 400
