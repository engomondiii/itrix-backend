from celery import shared_task
from django.core.management import call_command


@shared_task(name='website.deliver_mail', ignore_result=True)
def deliver_mail():
    from .services import deliver_outbox
    deliver_outbox()


@shared_task(name='website.expire_data', ignore_result=True)
def expire_data():
    call_command('expire_website_data')
