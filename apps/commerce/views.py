"""Explicit client, public and operator planes; no caller may set payment/verification state."""
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.db import IntegrityError
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from apps.clients.backends import ClientJWTAuthentication
from apps.clients.permissions import IsAuthenticatedClient
from apps.core.permissions import IsAdminRole
from . import services as svc
from .models import Branch, LegalRelease, License, Order, Refund, Reward


class SafeView(APIView):
    def handle_exception(self, exc):
        if isinstance(exc, ValidationError):
            return Response({'detail': exc.messages}, status=400)
        if isinstance(exc, (ObjectDoesNotExist, IntegrityError)):
            return Response({'detail': 'Record unavailable or action conflicts with its current state.'}, status=409)
        return super().handle_exception(exc)


class AvailabilityView(SafeView):
    authentication_classes = []
    permission_classes = [AllowAny]
    def get(self, request):
        from django.conf import settings
        enabled = bool(getattr(settings, 'ASTOP_COMMERCE_ENABLED', False) and
            getattr(settings, 'ASTOP_COMMERCE_ADAPTER', '') and LegalRelease.objects.filter(kind='lo', active=True).exists())
        return Response({'checkout_available': enabled, 'currency': 'USD', 'individual_seat_price': '20.00',
            'organization_seat_price': '16.00', 'organization_min_seats': 2, 'branch_discount_percent': 10,
            'discounts_stack': False, 'refund_request_days': 30,
            'message': 'Verified identity and License Order required.' if enabled else 'Contact itriX for access; online checkout is not available.'})


class ClientView(SafeView):
    authentication_classes = [ClientJWTAuthentication]
    permission_classes = [IsAuthenticatedClient]


def order_payload(order):
    return {'id': str(order.pk), 'kind': order.kind, 'seats': order.seats, 'amount': str(order.amount),
        'currency': order.currency, 'status': order.status, 'legal_body': order.legal_body,
        'legal_hash': order.legal_hash, 'legal_version': order.legal.version,
        'accepted_at': order.accepted_at, 'paid_at': order.paid_at}


class QuoteInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['individual', 'organization'])
    seats = serializers.IntegerField(min_value=1, max_value=10000)
    referral_code = serializers.CharField(required=False, allow_blank=True, max_length=32)


class OrdersView(ClientView):
    def get(self, request):
        return Response([order_payload(o) for o in Order.objects.filter(client=request.user).select_related('legal')[:100]])
    def post(self, request):
        data = QuoteInput(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(order_payload(svc.quote(client=request.user, **data.validated_data)), status=201)


class OrderActionView(ClientView):
    def post(self, request, order_id, action):
        # Never persist JWTs. Session evidence is a one-way hash, bound to authentication.
        if action == 'accept':
            return Response(order_payload(svc.accept_order(order_id=order_id, client=request.user,
                legal_hash=request.data.get('legal_hash', ''), session=request.headers.get('Authorization', ''))))
        if action == 'checkout':
            order = Order.objects.get(pk=order_id, client=request.user, status='accepted')
            # Provider MUST use order.id as idempotency key and disregard browser amounts.
            url = svc.adapter().checkout(order_id=str(order.pk), amount=str(order.amount), currency=order.currency)
            svc.require(isinstance(url, str) and url.startswith('https://'), 'Payment provider unavailable.')
            return Response({'url': url})
        if action == 'refund':
            refund = svc.request_refund(order_id=order_id, client=request.user, reason=str(request.data.get('reason', '')))
            return Response({'id': str(refund.pk), 'status': refund.status})
        return Response(status=404)


class LicensesView(ClientView):
    def get(self, request):
        return Response([{'id': str(l.pk), 'order_id': str(l.order_id), 'status': l.status,
            'seats': l.order.seats, 'assignments': list(l.assignments.filter(active=True).values('id', 'email'))}
            for l in License.objects.filter(order__client=request.user).select_related('order')[:100]])


class LicenseActionView(ClientView):
    def post(self, request, license_id, action):
        if action == 'download':
            return Response({'url': svc.deliver(license_id=license_id, client=request.user, platform=request.data.get('platform', ''))})
        if action == 'activate':
            activation, token = svc.activate(license_id=license_id, client=request.user,
                environment_hash=str(request.data.get('environment_hash', '')))
            return Response({'token': token, 'expires_at': activation.valid_until})
        if action == 'seats':
            seat = svc.assign_seat(license_id=license_id, client=request.user,
                email=str(request.data.get('email', '')), replace_id=request.data.get('replace_id'))
            return Response({'id': str(seat.pk), 'email': seat.email})
        return Response(status=404)


class BranchView(ClientView):
    def get(self, request):
        branch = Branch.objects.filter(client=request.user).first()
        if not branch:
            return Response({'status': 'not_applied'})
        return Response({'id': str(branch.pk), 'status': branch.status, 'code': branch.code if branch.status == 'active' else None,
            'agreement_body': branch.agreement_body, 'agreement_hash': branch.agreement_hash,
            'rewards': list(Reward.objects.filter(branch=branch).values('id', 'amount', 'status', 'eligible_at')[:100])})
    def post(self, request):
        if request.data.get('action') == 'accept':
            svc.accept_branch(client=request.user, legal_hash=request.data.get('legal_hash', ''),
                session=request.headers.get('Authorization', ''))
        else:
            svc.apply_branch(client=request.user, order_id=request.data.get('order_id'))
        return self.get(request)


class PaymentWebhookView(SafeView):
    authentication_classes = []
    permission_classes = [AllowAny]
    def post(self, request):
        # Signature, replay timestamp and provider account verification occur inside adapter.
        event = svc.adapter().verify_webhook(request.body, request.headers)
        svc.require(event.get('verified') is True, 'Provider verification failed.')
        if event.get('kind') in ('chargeback', 'refund'):
            svc.record_reversal(order_id=event['order_id'], provider_id=event['id'],
                payload_hash=svc.digest(request.body.decode('utf-8')), kind=event['kind'])
            return Response({'received': True})
        svc.require(event.get('kind') == 'capture', 'Unsupported event; operator review required.')
        svc.record_payment(order_id=event['order_id'], provider_id=event['id'],
            payment_reference=event['payment_reference'], amount=event['license_fee'],
            currency=event['currency'], payload_hash=svc.digest(request.body.decode('utf-8')))
        return Response({'received': True})


class OperatorView(SafeView):
    permission_classes = [IsAdminRole]
    def get(self, request):
        return Response({'orders': list(Order.objects.values('id', 'status', 'amount', 'seats', 'created_at')[:100]),
            'refunds': list(Refund.objects.values('id', 'order_id', 'status', 'reason', 'created_at')[:100]),
            'branches': list(Branch.objects.values('id', 'client_id', 'status', 'created_at')[:100])})
    def post(self, request):
        action, data = request.data.get('action'), request.data
        if action == 'verify_identity':
            from apps.clients.models import Client
            obj = svc.verify_identity(client=Client.objects.get(pk=data.get('client_id')), kind=data.get('kind'),
                details=data.get('details', {}), actor=request.user)
        elif action == 'publish_legal':
            obj = svc.publish_legal(kind=data.get('kind'), version=str(data.get('version', '')),
                body=str(data.get('body', '')), actor=request.user)
        elif action == 'approve_refund':
            obj = svc.approve_refund(refund_id=data.get('id'), actor=request.user)
        elif action == 'repay_refund':
            obj = svc.repay_refund(data.get('id'))
        elif action == 'approve_branch':
            obj = svc.approve_branch(branch_id=data.get('id'), actor=request.user)
        elif action in ('suspend_license', 'restore_license', 'revoke_license'):
            obj = svc.review_license(license_id=data.get('id'), actor=request.user,
                action=action.split('_')[0], review_reference=data.get('review_reference'))
        elif action == 'release_reward':
            obj = svc.release_reward(reward_id=data.get('id'), actor=request.user,
                settlement_reference=data.get('settlement_reference'), fraud_review_reference=data.get('fraud_review_reference'))
        else:
            return Response({'detail': 'Unsupported operator action.'}, status=400)
        return Response({'id': str(obj.pk)})
