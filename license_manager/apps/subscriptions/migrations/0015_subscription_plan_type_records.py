from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields

from license_manager.apps.subscriptions.constants import SUBSCRIPTION_PLAN_TYPES


def create_subscription_types(apps, schema_editor):
    """
    Create the enterprise subscription types if they do not already exist.
    """
    SubscriptionPlanType = apps.get_model('subscriptions', 'SubscriptionPlanType')
    for type_slug, type_name in SUBSCRIPTION_PLAN_TYPES.items():
        SubscriptionPlanType.objects.update_or_create(slug=type_slug, name=type_name)


def delete_subscription_types(apps, schema_editor):
    """
    Delete the enterprise subscription plan types.
    """
    SubscriptionPlanType = apps.get_model('subscriptions', 'SubscriptionPlanType')
    SubscriptionPlanType.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0014_create_cust_subscription_and_plan_type'),
    ]

    operations = [
        migrations.RunPython(create_subscription_types, delete_subscription_types),
    ]
