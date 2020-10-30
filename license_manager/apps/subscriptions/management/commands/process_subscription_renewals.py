import logging
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from license_manager.apps.subscriptions.exceptions import InsufficientLicensesForRenewalError
from license_manager.apps.subscriptions.models import (
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Processes all subscription renewals that should take effect on the day the command is run.'
        ' The processing renews each linked subscription and adjusts its metadata based on the terms specified in the'
        ' renewal.'
    )

    def handle(self, *args, **options):
        # Get all of the subscription renewals that should go into effect today, along with their linked subscriptions
        # and licenses.
        renewals_for_today = SubscriptionPlanRenewal.objects.filter(
            effective_date=datetime.today().date(),
        ).select_related(
            'subscription_plan',
        ).prefetch_related(
            'subscription_plan__licenses'
        )
        num_renewals_processed = 0
        mark_job_as_failed = False

        for renewal in renewals_for_today:
            message = 'Processing renewal: {renewal}'.format(renewal=renewal)
            logger.info(message)
            subscription_for_renewal = renewal.subscription_plan
            # Process each renewal atomically so that a subscription is not changed if there is an error during renewal
            try:
                with transaction.atomic():
                    subscription_for_renewal.start_date = renewal.effective_date
                    subscription_for_renewal.expiration_date = renewal.renewed_expiration_date
                    subscription_for_renewal.num_revocations_applied = 0
                    # Do we need fancier logic around `is_active` here?
                    subscription_for_renewal.is_active = True
                    subscription_for_renewal.save()

                    num_new_licenses = renewal.number_of_licenses - subscription_for_renewal.licenses.count()
                    if num_new_licenses == 0:
                        # If there is no change in licenses, great! Don't do anything
                        pass
                    elif num_new_licenses < 0:
                        num_licenses_to_remove = abs(num_new_licenses)
                        # Get the number of unassigned licenses in the subscription for renewal. As long as it's greater
                        # than or equal to the number of new licenses being added, we can just get rid of those
                        # unassigned licenses.
                        existing_unassigned_licenses = subscription_for_renewal.unassigned_licenses
                        if existing_unassigned_licenses.count() >= num_licenses_to_remove:
                            # TODO: Is it ok to delete these licenses? Should they be detached from the subscription? What's the
                            # best thing from a data preservation standpoint?
                            # Best thing long term is probably soft-deleting the licenses.
                            # See: https://medium.com/@adriennedomingus/soft-deletion-in-django-e4882581c340 or similar posts
                            unassigned_licenses_to_delete = existing_unassigned_licenses[:num_licenses_to_remove]
                            # You cannot use 'limit' or 'offset' with delete, so we delete these one at a time in a
                            # loop. It's not great performance wise, but this is a rare edge case that we don't expect
                            # to happen on large numbers of licenses.
                            for unassigned_license in unassigned_licenses_to_delete:
                                unassigned_license.delete()
                        else:
                            # TODO: Notify ECS. Likely needs a ticket for the full handling, email template, etc.
                            raise InsufficientLicensesForRenewalError(
                                renewal,
                                num_licenses_to_remove,
                                existing_unassigned_licenses.count(),
                            )
                    else:
                        # Another easy situation, they're just adding more licenses
                        subscription_for_renewal.increase_num_licenses(num_new_licenses)
            except InsufficientLicensesForRenewalError as exc:
                logger.error(exc)
                # We should fail the entire job if one goes wrong, but finish processing the rest first
                mark_job_as_failed = True
                continue
            num_renewals_processed += 1
            message = 'Successfully processed renewal: {renewal}'.format(renewal=renewal)
            logger.info(message)

        message = (
            'Successfully processed {num_renewals_processed} out of {total_renewals_for_today} subscription renewal(s)'
        ).format(
            num_renewals_processed=num_renewals_processed,
            total_renewals_for_today=renewals_for_today.count(),
        )
        logger.info(message)
        if mark_job_as_failed:
            num_failed_renewals = renewals_for_today.count() - num_renewals_processed
            error_message = '{num_failed_renewals} subscription renewal(s) were unable to be processed'.format(
                num_failed_renewals=num_failed_renewals,
            )
            raise Exception(error_message)
