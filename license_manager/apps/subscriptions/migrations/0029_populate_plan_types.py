import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)

def populate_plan(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    PlanType = apps.get_model("subscriptions", "PlanType")
    for row in SubscriptionPlan.objects.all():
        label_name = 'Test'
        if row.netsuite_product_id == 0:
            label_name = 'OCE'
            plan = PlanType.objects.get(label=label_name)
        elif row.netsuite_product_id == 106 or row.netsuite_product_id == 110:
            label_name - 'Standard Paid'
            plan = PlanType.objects.get(label=label_name)        
        else:
            plan = PlanType.objects.get(label=label_name)
        row.PlanType = plan
        row.save()
        message = 'Assigned {} label to subscription plan \"{}\"'.format(label_name, row.title)
        logger.info(message)

class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0028_plan_type_help_text'),
    ]

    operations = [
        migrations.RunPython(populate_plan),
    ]
