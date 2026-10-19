from django.core.management.base import BaseCommand
from apps.website.services import deliver_outbox
class Command(BaseCommand):
    help = 'Deliver pending website submission notifications; run every minute.'
    def handle(self, **options):
        deliver_outbox()
