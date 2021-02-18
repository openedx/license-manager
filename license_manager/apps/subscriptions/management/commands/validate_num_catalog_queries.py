import logging

from django.core.management.base import BaseCommand

from license_manager.apps.subscriptions.tasks import validate_query_mapping_task


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Verify that the correct number of distinct Catalog Queries used by Enterprise Catalogs for '
        'all SubscriptionPlans in the license-manager service exist in the enterprise-catalog service.'
    )

    def handle(self, *args, **options):
        validate_query_mapping_task.delay()
