import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0006_create_subscription_learner_role'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalsubscriptionplan',
            name='netsuite_product_id',
            field=models.IntegerField(default=1, help_text='Locate the Sales Order record in NetSuite and copy the Product ID field (numeric).'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='historicalsubscriptionplan',
            name='salesforce_opportunity_id',
            field=models.CharField(default='000000000000ABCABC', help_text='Locate the appropriate Salesforce Opportunity record and copy the Opportunity ID field (18 characters).', max_length=18, validators=[django.core.validators.MinLengthValidator(18)]),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscriptionplan',
            name='netsuite_product_id',
            field=models.IntegerField(default=1, help_text='Locate the Sales Order record in NetSuite and copy the Product ID field (numeric).'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscriptionplan',
            name='salesforce_opportunity_id',
            field=models.CharField(default='000000000000ABCABC', help_text='Locate the appropriate Salesforce Opportunity record and copy the Opportunity ID field (18 characters).', max_length=18, validators=[django.core.validators.MinLengthValidator(18)]),
            preserve_default=False,
        ),
    ]
