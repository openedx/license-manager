import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from license_manager.apps.api.tasks import license_expiration_task
from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    LICENSE_EXPIRATION_BATCH_SIZE,
)
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.utils import (
    chunks,
    localized_datetime_from_datetime,
    localized_utcnow,
)


logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'


class Command(BaseCommand):
    help = (
        'Gets all subscriptions that have expired within a time range (default range is the last 24 hours) and sends an'
        ' task to terminate the enrollments any licensed users have.'

        '\nIn the event the daily job fails and this needs to be run manually for subscriptions that expired more '
        'than 24 hours ago this can be done by specifying ``days_since_expiration`` as an arg'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--expired-after',
            action='store',
            dest='expiration_date_from',
            help='The oldest expiration date for subscriptions to be processed, can be used with --expired-before to '
                 'set a date range formatted as %Y-%m-%dT%H:%M:%S',
            default=(localized_utcnow() - timedelta(days=1)).strftime(DATE_FORMAT)
        )

        parser.add_argument(
            '--expired-before',
            action='store',
            dest='expiration_date_to',
            help='The most recent expiration date for subscriptions to be processed, can be used with --expired-after '
                 'to set a date range formatted as %Y-%m-%dT%H:%M:%S',
            default=localized_utcnow().strftime(DATE_FORMAT)
        )

        parser.add_argument(
            '--dry-run',
            action='store',
            dest='dry_run',
            help='Used to see which subscriptions would be processed by running this command without making changes',
            default=False
        )

        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            default=False,
        )

    def handle(self, *args, **options):
        expired_after_date = localized_datetime_from_datetime(
            datetime.strptime(options['expiration_date_from'], DATE_FORMAT))
        expired_before_date = localized_datetime_from_datetime(
            datetime.strptime(options['expiration_date_to'], DATE_FORMAT))

        now = localized_utcnow()

        if expired_after_date > now or expired_before_date > now:
            message = 'Subscriptions with expiration dates between {} and {} have not expired yet.'.format(
                expired_after_date,
                expired_before_date
            )
            logger.error(message)
            return

        filters = {'expiration_date__range': (expired_after_date, expired_before_date)}
        # process plans again if force flag = True
        if not options['force']:
            filters['expiration_processed'] = False

        expired_subscription_plans = SubscriptionPlan.objects.filter(
            **filters
        ).select_related('customer_agreement').prefetch_related('licenses')

        if not expired_subscription_plans:
            message = 'No subscriptions have expired between {} and {}'.format(
                expired_after_date, expired_before_date)
            logger.info(message)
            return

        if not options['dry_run']:
            for expired_subscription_plan in expired_subscription_plans:
                expired_licenses = [lcs for lcs in expired_subscription_plan.licenses.all() if lcs.status in [ASSIGNED, ACTIVATED]]
                any_failures = False

                # Terminate the licensed course enrollments for the given licenses,
                # an alert will be triggered if any failures occur
                for license_chunk in chunks(expired_licenses, LICENSE_EXPIRATION_BATCH_SIZE):
                    try:
                        license_chunk_uuids = [str(lcs.uuid) for lcs in license_chunk]
                        license_expiration_task(license_chunk_uuids)
                    except Exception:  # pylint: disable=broad-except
                        any_failures = True

                if not any_failures:
                    expired_subscription_plan.expiration_processed = True
                    expired_subscription_plan.save()

                    message = 'Terminated course enrollments for learners in subscription: {}'.format(
                        expired_subscription_plan.uuid)
                    logger.info(message)

                    expired_subscription_plan.expiration_processed = True
                    expired_subscription_plan.save(update_fields=['expiration_processed'])
                else:
                    message = 'Failed to process expiration for subscription: {}'.format(expired_subscription_plan.uuid)
                    logger.error(message)
        else:
            message = 'Dry-run result subscriptions that would be processed: {}'.format(
                [str(sub.uuid) for sub in expired_subscription_plans])
            logger.info(message)
