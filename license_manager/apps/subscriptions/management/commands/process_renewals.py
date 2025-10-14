import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand

from license_manager.apps.subscriptions.api import (
    RenewalProcessingError,
    renew_subscription,
)
from license_manager.apps.subscriptions.models import SubscriptionPlanRenewal
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Process subscription plan renewals with an upcoming (within the next 12 hours by default) effective date.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--processing-window-length-hours',
            action='store',
            dest='processing_window_length_hours',
            help='The length of the renewal processing window in hours, the default is 12 hours (e.g. renewals with an effective date within the next 12 hours will be processed)',
            default=(settings.SUBSCRIPTION_PLAN_RENEWAL_LOCK_PERIOD_HOURS)
        )

        parser.add_argument(
            '--dry-run',
            action='store',
            dest='dry_run',
            help='Used to see which subscriptions would be renewed by running this command without making changes',
            default=False
        )

    worker = None

    def handle(self, *args, **options):
        now = localized_utcnow()
        renewal_processing_window_cutoff = now + timedelta(hours=int(options['processing_window_length_hours']))

        renewals_to_be_processed = SubscriptionPlanRenewal.objects.filter(
            effective_date__gte=now, effective_date__lte=renewal_processing_window_cutoff, processed=False, exempt_from_batch_processing=False,
        ).select_related(
            'prior_subscription_plan',
            'prior_subscription_plan__customer_agreement',
            'renewed_subscription_plan'
        )

        subscription_uuids = [str(renewal.prior_subscription_plan.uuid) for renewal in renewals_to_be_processed]

        if not options['dry_run']:
            logger.info('Processing {} renewals for subscriptions with uuids: {}'.format(
                len(subscription_uuids), subscription_uuids))

            renewed_subscription_uuids = []
            for renewal in renewals_to_be_processed:
                subscription_uuid = str(renewal.prior_subscription_plan.uuid)
                try:
                    renew_subscription(renewal, is_auto_renewed=True)
                    renewed_subscription_uuids.append(subscription_uuid)
                except RenewalProcessingError:
                    logger.error('Could not automatically process renewal with id: {}'.format(
                        renewal.id), exc_info=True)

            logger.info('Processed {} renewals for subscriptions with uuids: {}'.format(
                        len(renewed_subscription_uuids), renewed_subscription_uuids))
        else:
            logger.info('Dry-run result subscriptions that would be renewed: {} '.format(
                        subscription_uuids))
