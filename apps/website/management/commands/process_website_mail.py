from django.core.management.base import BaseCommand
from apps.website.services import deliver_outbox
class Command(BaseCommand):
    help = 'Deliver pending website submission notifications; run every minute.'
    def handle(self, **options):
        deliver_outbox()
        from apps.website.models import Outbox
        pending = Outbox.objects.filter(sent_at__isnull=True, submission__deleted_at__isnull=True)
        self.stdout.write(f'Pending notifications: {pending.count()}; retried: {pending.filter(attempts__gt=0).count()}')
