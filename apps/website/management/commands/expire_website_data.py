from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.website.models import Submission, AdminSession, Audit, Subscription
from apps.website.views import redact
class Command(BaseCommand):
    help = 'Redact expired website submissions and remove expired sessions; run daily.'
    def handle(self, **options):
        now = timezone.now()
        cutoff = now - timedelta(days=settings.WEBSITE_RETENTION_DAYS)
        for obj in Submission.objects.filter(created_at__lt=cutoff, deleted_at__isnull=True).iterator():
            reference = obj.reference
            redact(obj)
            Audit.objects.create(actor='retention', action='deleted', target=reference)
        Subscription.objects.filter(consent_at__lt=cutoff).delete()
        AdminSession.objects.filter(last_activity__lt=now - timedelta(minutes=30)).delete()
        Audit.objects.filter(created_at__lt=now - timedelta(days=max(366, settings.WEBSITE_AUDIT_RETENTION_DAYS))).delete()
