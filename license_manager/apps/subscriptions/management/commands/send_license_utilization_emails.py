import logging

from django.core.management.base import BaseCommand

from license_manager.apps.api.tasks import send_initial_utilization_email_task
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Send email alerts to enterprise admins about license utilization of plans with auto-applied licenses.'
    )

    def handle(self, *args, **options):
        now = localized_utcnow()

        subscriptions = SubscriptionPlan.objects.filter(
            should_auto_apply_licenses=True,
            is_active=True,
            start_date__lte=now,
            expiration_date__gte=now
        ).select_related('customer_agreement')

        if not subscriptions:
            logger.info('No subscriptions with auto-applied licenses found, skipping license-utilization emails.')
            return

        for subscription in subscriptions:
            send_initial_utilization_email_task.delay(subscription.uuid)
