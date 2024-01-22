"""
Management command for making instances of models with test factories.
"""

from edx_django_utils.data_generation.management.commands.manufacture_data import \
    Command as BaseCommand

from license_manager.apps.subscriptions.tests.factories import *


class Command(BaseCommand):
    """
    Management command for generating Django records from factories with custom attributes

    Example usage:
        TODO
        $ ./manage.py manufacture_data --model license_manager.apps.subscriptions.models.SubscriptionPlan /
            --title "Test Subscription Plan"
    """
