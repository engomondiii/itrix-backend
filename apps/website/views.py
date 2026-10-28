"""Public intake and an independent, server-checked website administrator plane."""
import csv
import io
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError, APIException
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from . import services as s
from .models import Submission, Note, Notice, Audit, Outbox, Subscription, AdminIdentity
from .policy import store_policy


class WebsiteThrottle(SimpleRateThrottle):
    scope = 'website'
    rate = '30/hour'
    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': s.ip(request) or self.get_ident(request)}


class WebsiteOperationsRetired(APIException):
    status_code = 410
    default_detail = 'Website submissions are now handled through Google Forms. The website administrator console is retired.'
    default_code = 'website_operations_retired'


class PublicView(APIView):
    def initial(self, request, *args, **kwargs):
        if not settings.WEBSITE_NATIVE_OPERATIONS_ENABLED and self.__class__.__name__ not in {'Configuration', 'Unsubscribe'}:
            raise WebsiteOperationsRetired()
        return super().initial(request, *args, **kwargs)

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [WebsiteThrottle]


class Configuration(PublicView):
    throttle_classes = []
    def get(self, request):
        notice = Notice.objects.filter(pk=1, enabled=True).first()
        now = timezone.now()
        visible = notice and (not notice.starts_at or notice.starts_at <= now) and (not notice.ends_at or notice.ends_at > now)
        return Response({'store': store_policy(), 'notice': notice.content if visible and settings.WEBSITE_NATIVE_OPERATIONS_ENABLED else None,
                         'notice_ends_at': notice.ends_at if visible else None,
                         'captcha_site_key': settings.WEBSITE_TURNSTILE_SITE_KEY if settings.WEBSITE_NATIVE_OPERATIONS_ENABLED else '',
                         'privacy_version': settings.WEBSITE_PRIVACY_VERSION,
                         'intake_enabled': settings.WEBSITE_NATIVE_OPERATIONS_ENABLED and settings.WEBSITE_INTAKE_ENABLED, 'intake_provider': 'google_forms', 'forms': {'poc': 'https://forms.gle/FoGcs7LHhoTbmhtf8', 'contact': 'https://forms.gle/PCW2J9SF4wjDcPtA6', 'partnership': 'https://forms.gle/aACxKK1oggHiA8ueA'}})


class IntakeInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['poc', 'contact', 'interest'])
    language = serializers.ChoiceField(choices=['ko', 'en'], default='ko')
    company = serializers.CharField(max_length=200, required=False, allow_blank=True)
    name = serializers.CharField(max_length=200)
    email = serializers.EmailField(max_length=254)
    privacy = serializers.BooleanField()
    newsletter = serializers.BooleanField(default=False)
    privacy_version = serializers.CharField(max_length=80)
    request_id = serializers.UUIDField()
    captcha = serializers.CharField(max_length=4096, write_only=True)
    fields = serializers.DictField(child=serializers.CharField(max_length=6000, allow_blank=True), default=dict)
    def validate(self, value):
        if not value['privacy'] or value['privacy_version'] != settings.WEBSITE_PRIVACY_VERSION:
            raise ValidationError({'privacy': 'Accept the current privacy notice.'})
        if value['kind'] == 'poc' and not (value.get('company') and value['fields'].get('use')):
            raise ValidationError({'company': 'Company and target workload are required.'})
        if value['kind'] == 'contact' and not value['fields'].get('message'):
            raise ValidationError({'message': 'A message is required.'})
        permitted = {'role', 'phone', 'industry', 'tools', 'when', 'use', 'message', 'topic', 'platform', 'inquiry_route', 'partnership_type'}
        if set(value['fields']) - permitted:
            raise ValidationError({'fields': 'Unknown fields.'})
        if value['newsletter'] and value['kind'] != 'poc':
            raise ValidationError({'newsletter': 'News opt-in is available on the PoC form.'})
        return value


class Intake(PublicView):
    def post(self, request):
        if not settings.WEBSITE_INTAKE_ENABLED:
            return Response({'detail': 'Submissions are not open yet. Contact admin@itrix.co.kr.'}, status=503)
        data = IntakeInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        v['email'] = v['email'].strip().lower()
        s.captcha(v.pop('captcha'), s.ip(request))
        with transaction.atomic():
            prior = Submission.objects.filter(request_id=v['request_id']).first()
            if prior:
                # Never expose another applicant's record through a guessed idempotency key.
                if prior.email != v['email'] or prior.kind != v['kind']:
                    raise ValidationError('Request identifier already used.')
                return Response({'reference': prior.reference}, status=200)
            newsletter = v.pop('newsletter')
            v.pop('privacy')
            v['email'] = v['email'].strip().lower()
            # get_or_create handles concurrent retries of the same UUID using the
            # unique constraint and its own savepoint, without duplicate outbox rows.
            request_id = v.pop('request_id')
            obj, created = Submission.objects.get_or_create(request_id=request_id, defaults={
                **v, 'privacy_at': timezone.now(), 'ip': s.ip(request),
                'newsletter_at': timezone.now() if newsletter else None})
            if not created:
                if obj.email != v['email'] or obj.kind != v['kind']:
                    raise ValidationError('Request identifier already used.')
                return Response({'reference': obj.reference}, status=200)
            if newsletter:
                Subscription.objects.update_or_create(email=obj.email, defaults={'language': obj.language, 'subscribed': True, 'consent_at': timezone.now()})
            Outbox.objects.create(submission=obj, recipient=obj.email, role='applicant')
            for recipient in settings.WEBSITE_ALERT_EMAILS.split(','):
                if recipient.strip():
                    Outbox.objects.create(submission=obj, recipient=recipient.strip(), role='admin')
        if getattr(settings, 'ENABLE_CELERY', False):
            try:
                from .tasks import deliver_mail
                deliver_mail.delay()
            except Exception:
                pass  # Durable outbox + beat retries broker outages without losing intake.
        # Persistent outbox is retried by a management command; intake succeeds even during SMTP outage.
        return Response({'reference': obj.reference}, status=201)


class SignInInput(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    language = serializers.ChoiceField(choices=['ko', 'en'], default='ko')
    code = serializers.RegexField(r'^\d{6}$', required=False)


class SignIn(PublicView):
    def post(self, request, action):
        data = SignInInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if action == 'request':
            try:
                s.request_code(request, v['email'], v['language'])
            except (ValidationError, serializers.ValidationError):
                raise
            except Exception as exc:
                from rest_framework.exceptions import APIException
                if isinstance(exc, APIException):
                    raise
                return Response({'detail': 'Email delivery failed. Please try again later.'}, status=503)
            return Response({'sent': True, 'expires_in': 300})
        if action == 'verify':
            token = s.verify_code(request, v['email'], v.get('code', ''))
            # Only the same-origin BFF consumes this; it creates a scoped HttpOnly cookie.
            return Response({'session_token': token, 'idle_seconds': 1800})
        return Response(status=404)


class AdminView(PublicView):
    throttle_classes = []
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.admin_session = s.session(request, touch=request.method != 'GET')
        self.actor = self.admin_session.identity_id


class Session(AdminView):
    def get(self, request):
        return Response({'email': self.actor, 'language': self.admin_session.identity.language,
                         'expires_at': self.admin_session.last_activity + timedelta(minutes=30)})
    def post(self, request):
        if request.data.get('action') == 'logout':
            self.admin_session.delete()
        elif request.data.get('language') in ('ko', 'en'):
            self.admin_session.identity.language = request.data['language']
            self.admin_session.identity.save(update_fields=['language'])
        return Response({'ok': True})


def records(request):
    q = Submission.objects.filter(deleted_at__isnull=True)
    kind = request.query_params.get('kind', 'poc')
    if kind not in ('poc', 'contact', 'interest'):
        raise ValidationError('Unknown submission type.')
    q = q.filter(kind=kind)
    status = request.query_params.get('status', '')
    if status:
        q = q.filter(status=status)
    term = request.query_params.get('q', '')[:200].strip()
    if term:
        q = q.filter(Q(company__icontains=term) | Q(name__icontains=term) | Q(email__icontains=term))
    return q.order_by('-created_at')


def record(obj):
    return {'id': obj.pk, 'reference': obj.reference, 'kind': obj.kind, 'language': obj.language,
            'company': obj.company, 'name': obj.name, 'email': obj.email, 'fields': obj.fields,
            'status': obj.status, 'read_at': obj.read_at, 'created_at': obj.created_at,
            'privacy_at': obj.privacy_at, 'privacy_version': obj.privacy_version,
            'newsletter_at': obj.newsletter_at, 'ip': obj.ip}


class Records(AdminView):
    def get(self, request):
        q = records(request)
        base = Submission.objects.filter(deleted_at__isnull=True, kind=request.query_params.get('kind', 'poc'))
        try:
            offset = max(0, min(1000000, int(request.query_params.get('offset', '0'))))
        except ValueError:
            raise ValidationError('Invalid page offset.')
        notice = Notice.objects.filter(pk=1).first()
        now = timezone.now()
        return Response({'results': [record(o) for o in q[offset:offset+100]], 'total': q.count(),
            'counts': dict(base.values_list('status').annotate(n=Count('pk'))),
            'unread': base.filter(read_at__isnull=True).count(),
            'this_month': base.filter(created_at__year=now.year, created_at__month=now.month).count(),
            'days_left': max(0, (notice.ends_at - now).days) if notice and notice.ends_at else None})


class Record(AdminView):
    def get_object(self, pk):
        from django.shortcuts import get_object_or_404
        return get_object_or_404(Submission, pk=pk, deleted_at__isnull=True)
    def get(self, request, pk):
        obj = self.get_object(pk)
        # Viewing is explicitly auditable; polling session/list does not refresh inactivity.
        s.session(request, touch=True)
        if not obj.read_at:
            obj.read_at = timezone.now()
            obj.save(update_fields=['read_at'])
        s.audit(request, self.actor, 'viewed', obj.reference)
        return Response(dict(record(obj), notes=list(obj.note_set.values('author', 'text', 'created_at'))))
    def post(self, request, pk):
        with transaction.atomic():
            obj = self.get_object(pk)
            action = request.data.get('action')
            if action == 'status':
                statuses = ('new', 'review', 'active', 'done', 'hold') if obj.kind == 'poc' else ('new', 'replied', 'hold')
                if request.data.get('status') not in statuses:
                    raise ValidationError('Invalid status.')
                obj.status = request.data['status']
                obj.save(update_fields=['status'])
                s.audit(request, self.actor, 'status_change', obj.reference, status=obj.status)
            elif action == 'note':
                text = str(request.data.get('text', '')).strip()
                if not text or len(text) > 10000:
                    raise ValidationError('Enter a note of at most 10000 characters.')
                Note.objects.create(submission=obj, author=self.actor, text=text)
                s.audit(request, self.actor, 'note_added', obj.reference)
            elif action == 'delete' and request.data.get('confirm') is True:
                s.audit(request, self.actor, 'deleted', obj.reference)
                redact(obj)
            else:
                raise ValidationError('Unknown action or missing confirmation.')
        return Response({'ok': True})


def redact(obj):
    email = obj.email
    obj.name = obj.email = obj.company = ''
    obj.fields, obj.ip, obj.deleted_at = {}, None, timezone.now()
    obj.privacy_at = obj.created_at  # Keep only a non-identifying event timestamp.
    obj.newsletter_at = None
    obj.save()
    obj.note_set.all().delete()
    obj.outbox_set.all().delete()
    Subscription.objects.filter(email=email).delete()


class Export(AdminView):
    def post(self, request):
        if request.data.get('confirm') is not True:
            raise ValidationError('Confirm export of personal data.')
        q = records(request)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['Reference', 'Company', 'Name', 'Email', 'Status', 'Created', 'Language'])
        def safe(value):
            text = str(value)
            return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else text
        for obj in q.iterator():
            writer.writerow([safe(x) for x in [obj.reference, obj.company, obj.name, obj.email, obj.status, obj.created_at.isoformat(), obj.language]])
        s.audit(request, self.actor, 'csv_export', count=q.count())
        response = HttpResponse('\ufeff'+out.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="itrix-submissions.csv"'
        return response


class Logs(AdminView):
    def get(self, request):
        return Response(list(Audit.objects.order_by('-created_at').values('created_at', 'actor', 'action', 'target', 'ip', 'detail')[:500]))


class Accounts(AdminView):
    def get(self, request):
        existing = {a.email: a for a in AdminIdentity.objects.all()}
        return Response([{'email': email, 'level': 'administrator', 'last_login': existing[email].last_login if email in existing else None} for email in sorted(s.allowed())])


class NoticeInput(serializers.Serializer):
    enabled = serializers.BooleanField()
    starts_at = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    content = serializers.DictField()
    def validate(self, data):
        if data['starts_at'] and data['ends_at'] and data['starts_at'] >= data['ends_at']:
            raise ValidationError('End must follow start.')
        content = data['content']
        if set(content) != {'ko', 'en'}:
            raise ValidationError('Both Korean and English content are required.')
        for language in content.values():
            if not isinstance(language, dict) or set(language) != {'label', 'title', 'intro', 'rows', 'button', 'link'}:
                raise ValidationError('Complete all notice fields.')
            for key in ('label', 'title', 'intro', 'button', 'link'):
                if not isinstance(language[key], str) or len(language[key]) > 2000:
                    raise ValidationError('Invalid notice text.')
            # Only approved internal actions; no arbitrary script/external or Store CTA bypass.
            if language['link'] not in ('/poc', '/en/poc', '/contact', '/en/contact', '/#ask-chat', '/en#ask-chat'):
                raise ValidationError('Choose a PoC, Contact or Ask X link.')
            if not isinstance(language['rows'], list) or len(language['rows']) > 12:
                raise ValidationError('At most 12 information rows.')
            for row in language['rows']:
                if not isinstance(row, dict) or set(row) != {'label', 'value'} or any(not isinstance(v, str) or len(v) > 500 for v in row.values()):
                    raise ValidationError('Invalid information row.')
        return data


class NoticeEditor(AdminView):
    def get(self, request):
        obj, _ = Notice.objects.get_or_create(pk=1)
        return Response({'enabled': obj.enabled, 'starts_at': obj.starts_at, 'ends_at': obj.ends_at, 'content': obj.content})
    def post(self, request):
        data = NoticeInput(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            Notice.objects.update_or_create(pk=1, defaults=data.validated_data)
            s.audit(request, self.actor, 'notice_published', 'notice')
        return Response({'ok': True})


class Unsubscribe(PublicView):
    def get(self, request):
        obj = s.get_subscription(request.query_params.get('token', ''))
        name, domain = obj.email.split('@')
        return Response({'email': name[:1]+'***@'+domain, 'subscribed': obj.subscribed})
    def post(self, request):
        obj = s.get_subscription(str(request.data.get('token', '')))
        if type(request.data.get('subscribe')) is not bool:
            raise ValidationError('Choose a subscription preference.')
        obj.subscribed = request.data['subscribe']
        if obj.subscribed:
            obj.consent_at = timezone.now()
        obj.save()
        return Response({'subscribed': obj.subscribed})
