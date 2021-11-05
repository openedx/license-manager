import logging

from django.core.management.base import BaseCommand

from license_manager.apps.api.tasks import (
    send_utilization_threshold_reached_email_task,
    send_weekly_utilization_email_task,
)
from license_manager.apps.api_client.enterprise import EnterpriseApiClient
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

        api_client = EnterpriseApiClient()
        admin_users_by_enterprise_customer_uuid = {}

        for subscription in subscriptions:
            enterprise_customer_uuid = subscription.customer_agreement.enterprise_customer_uuid
            admin_users = admin_users_by_enterprise_customer_uuid.get(enterprise_customer_uuid)

            if admin_users is None:
                try:
                    admin_users = api_client.get_enterprise_admin_users(enterprise_customer_uuid)
                    admin_users_by_enterprise_customer_uuid[enterprise_customer_uuid] = admin_users
                except Exception:  # pylint: disable=broad-except
                    msg = f'Failed to retrieve enterprise admin users for {enterprise_customer_uuid}.'
                    logger.error(msg, exc_info=True)
                    continue

            email_recipients = [
                {
                    'ecu_id': user['ecu_id'],
                    'email': user['email'],
                    'created': user['created']
                }
                for user in admin_users
            ]

            subscription_details = {
                'uuid': subscription.uuid,
                'title': subscription.title,
                'enterprise_customer_uuid': subscription.enterprise_customer_uuid,
                'enterprise_customer_name': subscription.customer_agreement.enterprise_customer_name,
                'num_allocated_licenses': subscription.num_allocated_licenses,
                'num_licenses': subscription.num_licenses,
                'highest_utilization_threshold_reached': subscription.highest_utilization_threshold_reached
            }

            # logging is handled by tasks
            send_weekly_utilization_email_task.delay(subscription_details, email_recipients)
            send_utilization_threshold_reached_email_task.delay(subscription_details, email_recipients)
