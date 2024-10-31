
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    EXPIRED_LICENSE_UNLINKED,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    LicenseEvent,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Unlink expired licenses.'
    )

    def add_arguments(self, parser):
        """
        Entry point to add arguments.
        """
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            default=False,
            help='Dry Run, print log messages without unlinking the learners.',
        )

    def expired_licenses(self, log_prefix, enterprise_customer_uuid):
        """
        Get expired licenses.
        """
        now = localized_utcnow()
        expired_subscription_plan_uuids = []

        customer_agreement = CustomerAgreement.objects.get(enterprise_customer_uuid=enterprise_customer_uuid)

        # fetch expired subscription plans where the expiration date is older than 90 days.
        expired_subscription_plans = SubscriptionPlan.objects.filter(
            customer_agreement=customer_agreement,
            expiration_date__lt=now - timedelta(days=90),
        ).prefetch_related(
            'licenses'
        ).values('uuid', 'expiration_date')

        # log expired plan uuids and their expiration dates
        for plan in expired_subscription_plans:
            logger.info(
                '%s Expired plan. UUID: [%s], ExpirationDate: [%s]',
                log_prefix,
                plan.get('uuid'),
                plan.get('expiration_date')
            )

        expired_subscription_plan_uuids = [
            plan.get('uuid') for plan in expired_subscription_plans
        ]

        queryset = License.objects.filter(
            status__in=[ASSIGNED, ACTIVATED],
            renewed_to=None,
            subscription_plan__uuid__in=expired_subscription_plan_uuids,
        ).select_related(
            'subscription_plan',
        ).values('uuid', 'lms_user_id', 'user_email')

        # subquery to check for the existence of `EXPIRED_LICENSE_UNLINKED`
        event_exists_subquery = LicenseEvent.objects.filter(
            license=OuterRef('pk'),
            event_name=EXPIRED_LICENSE_UNLINKED
        ).values('pk')

        # exclude previously processed licenses.
        queryset = queryset.exclude(Exists(event_exists_subquery))

        return queryset

    def handle(self, *args, **options):
        """
        Unlink expired licenses.
        """
        unlink = not options['dry_run']

        log_prefix = '[UNLINK_EXPIRED_LICENSES]'
        if not unlink:
            log_prefix = '[DRY RUN]'

        logger.info('%s Command started.', log_prefix)

        enterprise_customer_uuids = settings.CUSTOMERS_WITH_EXPIRED_LICENSES_UNLINKING_ENABLED
        for enterprise_customer_uuid in enterprise_customer_uuids:
            logger.info('%s Unlinking started for licenses. Enterprise: [%s]', log_prefix, enterprise_customer_uuid)
            self.unlink_expired_licenses(log_prefix, enterprise_customer_uuid, unlink)
            logger.info('%s Unlinking completed for licenses. Enterprise: [%s]', log_prefix, enterprise_customer_uuid)

        logger.info('%s Command completed.', log_prefix)

    def unlink_expired_licenses(self, log_prefix, enterprise_customer_uuid, unlink):
        """
        Unlink expired licenses.
        """
        expired_licenses = self.expired_licenses(log_prefix, enterprise_customer_uuid)

        if not expired_licenses:
            logger.info(
                '%s No expired licenses were found for enterprise: [%s].',
                log_prefix, enterprise_customer_uuid
            )
            return

        paginator = Paginator(expired_licenses, 100)
        for page_number in paginator.page_range:
            licenses = paginator.page(page_number)

            license_uuids = []
            user_emails = []

            for license in licenses:
                # check if the user associated with the expired license
                # has any other active licenses with the same customer
                other_active_licenses = License.for_user_and_customer(
                    user_email=license.get('user_email'),
                    lms_user_id=license.get('lms_user_id'),
                    enterprise_customer_uuid=enterprise_customer_uuid,
                    active_plans_only=True,
                    current_plans_only=True,
                ).exists()
                if other_active_licenses:
                    continue

                license_uuids.append(license.get('uuid'))
                user_emails.append(license.get('user_email'))

            if unlink and user_emails:
                EnterpriseApiClient().bulk_unlink_enterprise_users(
                    enterprise_customer_uuid,
                    {
                        'user_emails': user_emails,
                        'is_relinkable': True
                    },
                )

                # Create license events for unlinked licenses to avoid processing them again.
                unlinked_license_events = [
                    LicenseEvent(license_id=license_uuid, event_name=EXPIRED_LICENSE_UNLINKED)
                    for license_uuid in license_uuids
                ]
                LicenseEvent.objects.bulk_create(unlinked_license_events, batch_size=100)

            logger.info(
                "%s learners unlinked for licenses. Enterprise: [%s], LicenseUUIDs: [%s].",
                log_prefix,
                enterprise_customer_uuid,
                license_uuids
            )
