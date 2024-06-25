
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    SegmentEvents,
)
from license_manager.apps.subscriptions.event_utils import track_event
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    LicenseEvent,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Trigger segment event for active licenses if license was activated 180 days ago.'
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
            help='Dry Run, print log messages without firing the segment event.',
        )

    def activated_licenses(self, enterprise_customer_uuid):
        """
        Get activated licenses.

        Fetch licenses where:
            * A user is a linked VSF learner.
            * They had a subscription license activated to them 180 days ago.
            * The license is still active.
        """
        now = localized_utcnow()

        customer_agreement = CustomerAgreement.objects.get(enterprise_customer_uuid=enterprise_customer_uuid)

        subscription_plan_uuids = list(customer_agreement.subscriptions.values_list('uuid', flat=True))

        queryset = License.objects.filter(
            subscription_plan__uuid__in=subscription_plan_uuids,
            subscription_plan__is_active=True,
            activation_date__lt=(now - timedelta(days=180)),
            status=ACTIVATED
        ).select_related(
            'subscription_plan',
        ).values('uuid', 'lms_user_id', 'user_email').order_by('activation_date')

        # Subquery to check for the existence of `LICENSE_ACTIVATED_180_DAYS_AGO` event
        event_exists_subquery = LicenseEvent.objects.filter(
            license=OuterRef('pk'),
            event_name=SegmentEvents.LICENSE_ACTIVATED_180_DAYS_AGO
        ).values('pk')

        # Exclude licenses that have the specific event
        queryset = queryset.exclude(Exists(event_exists_subquery))

        return queryset

    def handle(self, *args, **options):
        """
        Trigger segment event for active licenses if license was activated 180 days ago.
        """
        fire_event = not options['dry_run']

        log_prefix = '[SEND_LICENSE_ASSIGNED_180_DAYS_AGO_SEGMENT_EVENTS]'
        if not fire_event:
            log_prefix = '[DRY RUN]'

        logger.info('%s Command started.', log_prefix)

        enterprise_customer_uuids = settings.CUSTOMERS_WITH_CUSTOM_LICENSE_EVENTS
        for enterprise_customer_uuid in enterprise_customer_uuids:
            logger.info('%s Processing started for licenses. Enterprise: [%s]', log_prefix, enterprise_customer_uuid)
            self.trigger_events(enterprise_customer_uuid, log_prefix, fire_event)
            logger.info('%s Processing completed for licenses. Enterprise: [%s]', log_prefix, enterprise_customer_uuid)

        logger.info('%s Command completed.', log_prefix)

    def trigger_events(self, enterprise_customer_uuid, log_prefix, fire_event):
        """
        Trigger segment event for learners of an enterprise.
        """
        activated_licenses = self.activated_licenses(enterprise_customer_uuid)

        if not activated_licenses:
            logger.info(
                '%s No licenses were found that were activated by a learner 180 days ago.',
                log_prefix
            )
            return

        triggered_event_records = []
        paginator = Paginator(activated_licenses, 100)
        for page_number in paginator.page_range:
            licenses = paginator.page(page_number)

            user_ids = []
            for license in licenses:
                user_id = license.get('lms_user_id')
                user_ids.append(user_id)

                if fire_event:
                    track_event(
                        user_id,
                        SegmentEvents.LICENSE_ACTIVATED_180_DAYS_AGO,
                        {
                            'user_email': license.get('user_email'),
                        }
                    )
                    triggered_event_records.append(
                        LicenseEvent(
                            license_id=license.get('uuid'),
                            event_name=SegmentEvents.LICENSE_ACTIVATED_180_DAYS_AGO
                        )
                    )

            logger.info(
                "%s segment events triggered. Enterprise: [%s], UserIds: [%s].",
                log_prefix,
                enterprise_customer_uuid,
                user_ids
            )

            if triggered_event_records:
                LicenseEvent.objects.bulk_create(triggered_event_records, batch_size=100)
