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
            '--subscription-uuids',
            action='store',
            dest='subscription_uuids',
            help='Delimited subscription uuids used to specify which subscription plans should be expired.',
            type=lambda s: [str(uuid) for uuid in s.split(',')]
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

    def _expire_subscription_plan(self, expired_subscription_plan):
        """
        Expires a single subscription plan.
        """
        expired_licenses = []

        for lcs in expired_subscription_plan.licenses.iterator():
            if lcs.status in [ASSIGNED, ACTIVATED]:
                expired_licenses.append(lcs)

        any_failures = False

        # Terminate the licensed course enrollments
        for license_chunk in chunks(expired_licenses, LICENSE_EXPIRATION_BATCH_SIZE):
            try:
                license_chunk_uuids = [str(lcs.uuid) for lcs in license_chunk]

                # We might be running this command against a plan that expired further in the past to fix bad data. We don't
                # want to modify a course enrollment if it's been modified after the plan expiration because a user might have upgraded
                # the course.
                ignore_enrollments_modified_after = expired_subscription_plan.expiration_date.isoformat() \
                    if expired_subscription_plan.expiration_date < localized_utcnow() - timedelta(days=1) else None

                license_expiration_task(
                    license_chunk_uuids,
                    ignore_enrollments_modified_after=ignore_enrollments_modified_after
                )
            except Exception:  # pylint: disable=broad-except
                any_failures = True
                msg = 'Failed to terminate course enrollments for learners in subscription: {}'.format(
                    expired_subscription_plan.uuid)
                logger.exception(msg)

        if not any_failures:
            message = 'Terminated course enrollments for learners in subscription: {}'.format(
                expired_subscription_plan.uuid)
            logger.info(message)

            expired_subscription_plan.expiration_processed = True
            expired_subscription_plan.save(update_fields=['expiration_processed'])

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

        if options['subscription_uuids']:
            filters = {'uuid__in': options['subscription_uuids'], 'expiration_date__lte': now}
        else:
            filters = {'expiration_date__range': (expired_after_date, expired_before_date)}

            # process expired plans again if force flag = True
            if not options['force']:
                filters['expiration_processed'] = False

        expired_subscription_plans = SubscriptionPlan.objects.filter(
            **filters
        ).select_related('customer_agreement').prefetch_related('licenses')

        if not expired_subscription_plans:
            if options['subscription_uuids']:
                message = 'No subscriptions with uuids {} have expired'.format(
                    options['subscription_uuids'])
                logger.error(message)
                raise Exception(message)
            else:
                message = 'No subscriptions have expired between {} and {}'.format(
                    expired_after_date, expired_before_date)
                logger.info(message)
                return

        if not options['dry_run']:
            for expired_subscription_plan in expired_subscription_plans:
                renewal_for_plan = expired_subscription_plan.get_renewal()

                # If there is a renewal, we do not want to revoke licensed course enrollments
                # until the last renewed plan expires
                if renewal_for_plan:
                    msg = 'Not processing expiration for subscription: {}, plan has a renewal.'.format(
                        expired_subscription_plan.uuid)
                    logger.info(msg)
                    continue

                self._expire_subscription_plan(expired_subscription_plan)

                prior_renewals = expired_subscription_plan.prior_renewals

                # revoke licensed course enrollments for all previous plans
                for prior_renewal in prior_renewals:
                    self._expire_subscription_plan(prior_renewal.prior_subscription_plan)
        else:
            message = 'Dry-run result subscriptions that would be processed: {}'.format(
                [str(sub.uuid) for sub in expired_subscription_plans])
            logger.info(message)
