import logging

from django.core.management.base import BaseCommand

from license_manager.apps.subscriptions.models import SubscriptionPlan, PlanType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Automatically populates the subscription plan types using the netsuite product id.'
    )

    def handle(self, *args, **options):
        for row in SubscriptionPlan.objects.all():
            if row.netsuite_product_id == 0:
                plan = Command.save_plan(row, 'OCE')
            elif row.netsuite_product_id == 106 or row.netsuite_product_id == 110:
                plan = Command.save_plan(row, 'Standard Paid')
            else:
                plan = Command.save_plan(row, 'Test')
            row.PlanType = plan
            row.save()

    def save_plan(row, plan_label):
        message = 'Assigned {} label to subscription plan \"{}\"'.format(plan_label, row.title)
        logger.info(message)
        return PlanType.objects.get(label=plan_label)
