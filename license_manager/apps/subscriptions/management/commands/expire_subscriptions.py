import json
import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from rest_framework import status

from license_manager.apps.api.tasks import license_expiration_task
from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    LICENSE_EXPIRATION_BATCH_SIZE,
)
from license_manager.apps.subscriptions.models import License, SubscriptionPlan
from license_manager.apps.subscriptions.utils import (
    chunks,
    localized_datetime_from_datetime,
    localized_utcnow,
)


logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


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
                 'set a date range formatted as %Y-%m-%d %H:%M:%S',
            default=(localized_utcnow() - timedelta(days=1)).strftime(DATE_FORMAT)
        )

        parser.add_argument(
            '--expired-before',
            action='store',
            dest='expiration_date_to',
            help='The most recent expiration date for subscriptions to be processed, can be used with --expired-after '
                 'to set a date range formatted as %Y-%m-%d %H:%M:%S',
            default=localized_utcnow().strftime(DATE_FORMAT)
        )

        parser.add_argument(
            '--dry-run',
            action='store',
            dest='dry_run',
            help='Used to see which subscriptions would be processed by running this command without making changes',
            default=False
        )

    def handle(self, *args, **options):
        expired_after_date = localized_datetime_from_datetime(datetime.strptime(options['expiration_date_from'], DATE_FORMAT))
        expired_before_date = localized_datetime_from_datetime(datetime.strptime(options['expiration_date_to'], DATE_FORMAT))

        today = localized_utcnow()

        if expired_after_date > today or expired_before_date > today:
            message = 'Subscriptions with expiration dates between {} and {} have not expired yet.'.format(
                expired_after_date,
                expired_before_date
            )
            logger.error(message)
            return

        expired_licenses = License.objects.filter(
            subscription_plan__expiration_date__range=(expired_after_date, expired_before_date),
            status__in=[ASSIGNED, ACTIVATED],
        )

        if not expired_licenses:
            message = 'No subscriptions have expired between {} and {}'.format(expired_after_date, expired_before_date)
            logger.info(message)
            return

        expired_license_uuids = []
        expired_subscription_uuids = set({})
        for license in expired_licenses:
            expired_license_uuids.append(str(license.uuid))
            expired_subscription_uuids.add(str(license.subscription_plan.uuid))

        if not options['dry_run']:
            # Terminate the licensed course enrollments
            for license_uuids_chunk in chunks(expired_license_uuids, LICENSE_EXPIRATION_BATCH_SIZE):
                license_expiration_task(license_uuids_chunk)

            # Mark the expired subscriptions as having been processed
            expired_subscriptions = SubscriptionPlan.objects.filter(
                uuid__in=expired_subscription_uuids
            )
            expired_subscriptions.update(expiration_processed=True)

            message = 'Terminated course enrollments for learners in subscriptions: {} '.format(expired_subscription_uuids)
            logger.info(message)
        else:
            message = 'Dry-run result subscriptions that would be processed: {} '.format(
                expired_subscription_uuids)
            logger.info(message)
