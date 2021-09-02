import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand

from license_manager.apps.core.models import User
from license_manager.apps.subscriptions.api import (
    RenewalProcessingError,
    renew_subscription,
)
from license_manager.apps.subscriptions.constants import (
    PROCESS_SUBSCRIPTION_RENEWAL_AUTO_RENEWED,
)
from license_manager.apps.subscriptions.event_utils import track_event
from license_manager.apps.subscriptions.models import SubscriptionPlanRenewal
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)
LCM_WORKER_USERNAME = "license_manager_worker"


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

    def track_subscription_renewal(self, renewal):
        if self.worker:
            try:
                track_event(self.worker.id, PROCESS_SUBSCRIPTION_RENEWAL_AUTO_RENEWED, {
                    'user_id': self.worker.id,
                    'prior_subscription_plan_id': str(renewal.prior_subscription_plan.uuid),
                    'renewed_subscription_plan_id': str(renewal.renewed_subscription_plan.uuid)
                })
            except Exception as exc:  # pylint: disable=broad-except
                logger.info(exc)

    def handle(self, *args, **options):
        now = localized_utcnow()
        renewal_processing_window_cutoff = now + timedelta(hours=int(options['processing_window_length_hours']))

        renewals_to_be_processed = SubscriptionPlanRenewal.objects.filter(
            effective_date__gte=now, effective_date__lte=renewal_processing_window_cutoff, processed=False
        ).select_related(
            'prior_subscription_plan',
            'prior_subscription_plan__customer_agreement',
            'renewed_subscription_plan'
        )

        subscriptions_to_be_renewed_uuids = [str(renewal.prior_subscription_plan.uuid) for renewal in renewals_to_be_processed]

        if not options['dry_run']:
            logger.info('Processing {} renewals for subscriptions with uuids: {}'.format(
                len(subscriptions_to_be_renewed_uuids), subscriptions_to_be_renewed_uuids)
            )

            try:
                # get worker for sending tracking events to segment
                self.worker = User.objects.get(username=LCM_WORKER_USERNAME)
            except User.DoesNotExist:
                pass

            renewed_subscription_uuids = []
            for renewal in renewals_to_be_processed:
                subscription_uuid = str(renewal.prior_subscription_plan.uuid)
                try:
                    renew_subscription(renewal)
                    renewed_subscription_uuids.append(subscription_uuid)
                    self.track_subscription_renewal(renewal)
                except RenewalProcessingError:
                    logger.error('Could not automatically process renewal with id: {}'.format(renewal.id), exc_info=True)

            logger.info('Processed {} renewals for subscriptions with uuids: {}'.format(len(renewed_subscription_uuids), renewed_subscription_uuids))
        else:
            message = 'Dry-run result subscriptions that would be renewed: {} '.format(subscriptions_to_be_renewed_uuids)
            logger.info(message)
