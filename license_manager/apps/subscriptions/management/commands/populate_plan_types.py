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
                Command.save_plan(row, 'OCE')
            elif row.netsuite_product_id == 106 or row.netsuite_product_id == 110:
                Command.save_plan(row, 'Standard Paid')
            else:
                Command.save_plan(row, 'Test')

    def save_plan(row, label):
        plan = PlanType.objects.filter(label='OCE')
        row.PlanType = plan
        row.save()
        message = 'Assigned {} label to subscription plan \"{}\"'.format(label, row.title)
        logger.info(message)
