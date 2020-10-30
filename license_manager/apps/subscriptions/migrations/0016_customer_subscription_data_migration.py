from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import model_utils.fields

from license_manager.apps.subscriptions.constants import INITIAL_PLAN_TYPE


def create_relationships(apps, schema_editor):
    """
    Create relationships between existing SubscriptionPlans and new CustomerSubscriptions.
    """
    SubscriptionPlanType = apps.get_model('subscriptions', 'SubscriptionPlanType')
    initial_plan_type = SubscriptionPlanType.objects.get(slug=INITIAL_PLAN_TYPE)

    CustomerSubscription = apps.get_model('subscriptions', 'CustomerSubscription')

    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    for plan in SubscriptionPlan.objects.all():
        customer, was_created = CustomerSubscription.objects.get_or_create(
            enterprise_customer_uuid=plan.enterprise_customer_uuid
        )
        plan.customer_subscription = customer
        plan.subscription_plan_type = initial_plan_type
        plan.save()


def delete_relationships(apps, schema_editor):
    """
    Delete every CustomerSubscription and any links from plans to plan types or CustomerSubscriptions.
    """
    CustomerSubscription = apps.get_model('subscriptions', 'CustomerSubscription')
    CustomerSubscription.objects.all().delete()

    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    SubscriptionPlan.objects.all().update(subscription_plan_type=None)


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0015_subscription_plan_type_records'),
    ]

    operations = [
        migrations.RunPython(create_relationships, delete_relationships),
    ]
