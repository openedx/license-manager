from django.core.management.base import BaseCommand

from license_manager.apps.subscriptions.models import SubscriptionPlan, PlanType


class Command(BaseCommand):
    help = (
        'Automatically populates the subscription plan types using the netsuite product id.'
    )

    for row in SubscriptionPlan.objects.all():
        if row.netsuite_product_id == 0:
            plan = PlanType.objects.filter(label='OCE')
            row.PlanType = plan
        elif row.netsuite_product_id == 106 or row.netsuite_product_id == 110:
            plan = PlanType.objects.filter(label='Standard Paid')
            row.PlanType = plan
        else:
            plan = PlanType.objects.filter(label='Test')
            row.PlanType = plan
        
