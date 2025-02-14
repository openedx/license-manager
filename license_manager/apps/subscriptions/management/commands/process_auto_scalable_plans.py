import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from license_manager.apps.subscriptions.models import CustomerAgreement


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Executes auto-scaling on any eligible subscription plans.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Used to see which subscriptions would be auto-scaled by running this command without making changes',
            default=False
        )

    def handle(self, *args, **options):
        now = timezone.now()

        for agreement in CustomerAgreement.objects.filter(enable_auto_scaling_of_current_plan=True):
            logger.info('%s has auto-scaling enabled, checking if current plan needs auto-scaling executed', agreement)
            plan = agreement.subscriptions.filter(
                is_active=True,
                start_date__lte=now,
                expiration_date__gte=now
            ).order_by('-start_date').first()

            if not plan:
                logger.info('No current, active plan exists for %s', agreement)
                continue

            if not plan.num_licenses:
                logger.info('Current plan %s has no licenses, will not auto-scale', plan)
                continue

            # What percentage of unallocated licenses requires us to auto-scale?
            min_unallocated_license_required_percentage = 100.0 - agreement.auto_scaling_threshold_percentage

            # What percentage of licenses in the plan are unallocated?
            unallocated_licenses = plan.num_licenses - plan.num_allocated_licenses
            unallocated_license_percentage = (unallocated_licenses / plan.num_licenses) * 100.0

            if unallocated_license_percentage < min_unallocated_license_required_percentage:
                logger.info(
                    'Preparing to auto-scale %s, unallocated license count is %s, '
                    'unallocated percentage is %s, and min unallocated requirement is %s',
                    plan, unallocated_licenses,
                    unallocated_license_percentage, min_unallocated_license_required_percentage,
                )
                # We're not allowed to auto-apply beyond this hard limit.
                difference_from_upper_limit = agreement.auto_scaling_max_licenses - plan.num_licenses

                factor_to_increment_by = agreement.auto_scaling_increment_percentage / 100.0
                number_licenses_to_add = int(min(
                    plan.num_licenses * factor_to_increment_by,
                    difference_from_upper_limit
                ))
                if not options['dry_run']:
                    logger.info('Auto-scaling %s by %s licenses', plan, number_licenses_to_add)
                    plan.increase_num_licenses(number_licenses_to_add)
                    logger.info('Auto-scaling completed for %s', plan)
                else:
                    logger.info('Dry run; would auto-scale %s by %s licenses', plan, number_licenses_to_add)
            else:
                logger.info(
                    '%s does not require auto-scaling, unallocated license count is %s, '
                    'unallocated license percentage is %s, and min unallocated requirement is %s',
                    plan, unallocated_licenses,
                    unallocated_license_percentage, min_unallocated_license_required_percentage,
                )
