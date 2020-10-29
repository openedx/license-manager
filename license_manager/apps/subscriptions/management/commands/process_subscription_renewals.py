import logging
from datetime import datetime

from django.core.management.base import BaseCommand

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

        for renewal in renewals_for_today:
            subscription_for_renewal = renewal.subscription_plan
            message = 'Processing renewal with effective date: {} for subscription with uuid: {}'.format(
                renewal.effective_date,
                subscription_for_renewal.uuid,
            )
            logger.info(message)

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
                # Get the number of unassigned licenses in the subscription for renewal. As long as it's greater than
                # or equal to the number of new licenses being added, we can just get rid of those unassigned licenses.
                existing_unassigned_licenses = subscription_for_renewal.unassigned_licenses
                if existing_unassigned_licenses.count() >= num_new_licenses:
                    # TODO: Is it ok to delete these licenses? Should they be detached from the subscription? What's the
                    # best thing from a data preservation standpoint?
                    # Best thing long term is probably soft-deleting the licenses.
                    # See: https://medium.com/@adriennedomingus/soft-deletion-in-django-e4882581c340 or similar posts
                    unassigned_licenses_to_delete = existing_unassigned_licenses[:num_new_licenses]
                    unassigned_licenses_to_delete.delete()
                else:
                    # TODO: Figure out logic on what to do if they are trying to renew but don't have enough unassigned
                    # to pick from.
                    print('Not enough unassigned licenses')
            else:
                # Another easy situation, they're just adding more licenses
                subscription_for_renewal.increase_num_licenses(num_new_licenses)

            message = 'Successfully renewed subscription with uuid: {}'.format(
                subscription_for_renewal.uuid,
            )
            logger.info(message)

        message = 'Successfully processed {} subscription renewals'.format(
            renewals_for_today.count(),
        )
        logger.info(message)
