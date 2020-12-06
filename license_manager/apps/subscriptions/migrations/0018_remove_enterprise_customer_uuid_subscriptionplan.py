from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0017_support_customer_agreements'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='historicalsubscriptionplan',
            name='enterprise_customer_uuid',
        ),
        migrations.RemoveField(
            model_name='subscriptionplan',
            name='enterprise_customer_uuid',
        ),
    ]
