"""
Management command for seeding devstack with data for development.
"""


from django.core.management.base import BaseCommand

from license_manager.apps.subscriptions.models import PlanType, Product


class Command(BaseCommand):
    """
    Management command for populating License Manager data required for development.

    """

    help = 'Seeds all the data required for development.'

    def _create_products(self):
        Product.objects.get_or_create(
            name='B2B Paid',
            description='B2B Catalog',
            plan_type=PlanType.objects.get(label="Standard Paid"),
            netsuite_id=106
        )
        Product.objects.get_or_create(
            name='OC Paid',
            description='OC Catalog',
            plan_type=PlanType.objects.get(label="Standard Paid"),
            netsuite_id=110
        )
        Product.objects.get_or_create(
            name='Trial',
            description='Trial Catalog',
            plan_type=PlanType.objects.get(label="Trial")
        )
        Product.objects.get_or_create(
            name='Test',
            description='Test Catalog',
            plan_type=PlanType.objects.get(label="Test")
        )

    def handle(self, *args, **options):
        self._create_products()
