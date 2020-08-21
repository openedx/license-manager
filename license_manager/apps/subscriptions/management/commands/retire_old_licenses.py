import logging
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand

from license_manager.apps.subscriptions.constants import (
    ASSIGNED,
    DAYS_TO_RETIRE,
    DEACTIVATED,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.models import License


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Retire user data on licenses which have not been activated for over 90 days, have been revoked but not '
        ' reassigned for over 90 days, or whose associated subscription has expired for over 90 days.'
    )

    def _clear_historical_pii(self, license_obj):
        """
        Helper function to remove pii (user_email & lms_user_id) from the license's historical records.
        """
        license_obj.history.update(user_email=None, lms_user_id=None)

    def handle(self, *args, **options):
        # Any license that was assigned but not activated or revoked but not reassigned before this date should
        # have its data scrubbed.
        ready_for_retirement_date = datetime.today().date() - timedelta(DAYS_TO_RETIRE)

        expired_licenses_for_retirement = License.objects.filter(
            user_email__isnull=False,
            subscription_plan__expiration_date__lt=ready_for_retirement_date,
        )
        # Scrub all piii on licenses whose subscription expired over 90 days ago, and mark the licenses as revoked
        for expired_license in expired_licenses_for_retirement:
            expired_license.user_email = None
            expired_license.lms_user_id = None
            expired_license.status = DEACTIVATED
            expired_license.revoked_date = datetime.now()
            self._clear_historical_pii(expired_license)
        License.objects.bulk_update(
            expired_licenses_for_retirement,
            ['user_email', 'lms_user_id', 'status', 'revoked_date'],
        )
        expired_license_uuids = sorted([expired_license.uuid for expired_license in expired_licenses_for_retirement])
        message = 'Retired {} expired licenses with uuids: {}'.format(len(expired_license_uuids), expired_license_uuids)
        logger.info(message)

        revoked_licenses_for_retirement = License.objects.filter(
            status=DEACTIVATED,
            user_email__isnull=False,
            revoked_date__isnull=False,
            revoked_date__date__lt=ready_for_retirement_date,
        )
        # Scrub all pii on the revoked licenses, but they should stay revoked and keep their other info as we currently
        # add an unassigned license to the subscription's license pool whenever one is revoked.
        for revoked_license in revoked_licenses_for_retirement:
            revoked_license.user_email = None
            revoked_license.lms_user_id = None
            self._clear_historical_pii(revoked_license)
        License.objects.bulk_update(revoked_licenses_for_retirement, ['user_email', 'lms_user_id'])
        revoked_license_uuids = sorted([revoked_license.uuid for revoked_license in revoked_licenses_for_retirement])
        message = 'Retired {} revoked licenses with uuids: {}'.format(len(revoked_license_uuids), revoked_license_uuids)
        logger.info(message)

        assigned_licenses_for_retirement = License.objects.filter(
            status=ASSIGNED,
            assigned_date__isnull=False,
            assigned_date__date__lt=ready_for_retirement_date,
        )
        # We place previously assigned licenses that are now retired back into the unassigned license pool, so we scrub
        # all data on them.
        for assigned_license in assigned_licenses_for_retirement:
            assigned_license.reset_to_unassigned()
            self._clear_historical_pii(assigned_license)
        License.objects.bulk_update(
            assigned_licenses_for_retirement,
            [
                'status',
                'user_email',
                'lms_user_id',
                'last_remind_date',
                'activation_date',
                'activation_key',
                'assigned_date',
                'revoked_date',
            ],
        )
        assigned_license_uuids = sorted(
            [assigned_license.uuid for assigned_license in assigned_licenses_for_retirement],
        )
        message = 'Retired {} previously assigned licenses with uuids: {}'.format(
            len(assigned_license_uuids),
            assigned_license_uuids,
        )
        logger.info(message)
