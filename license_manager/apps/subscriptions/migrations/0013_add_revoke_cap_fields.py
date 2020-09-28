# Generated by Django 2.2.16 on 2020-09-28 19:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0012_remove_purchase_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalsubscriptionplan',
            name='num_revocations_applied',
            field=models.PositiveSmallIntegerField(blank=True, default=0, help_text='Number of revocations applied to Licenses for this SubscriptionPlan.', verbose_name='Number of Revocations Applied'),
        ),
        migrations.AddField(
            model_name='historicalsubscriptionplan',
            name='revoke_max_percentage',
            field=models.PositiveSmallIntegerField(blank=True, default=5, help_text='Percentage of Licenses that can be revoked for this SubscriptionPlan.'),
        ),
        migrations.AddField(
            model_name='subscriptionplan',
            name='num_revocations_applied',
            field=models.PositiveSmallIntegerField(blank=True, default=0, help_text='Number of revocations applied to Licenses for this SubscriptionPlan.', verbose_name='Number of Revocations Applied'),
        ),
        migrations.AddField(
            model_name='subscriptionplan',
            name='revoke_max_percentage',
            field=models.PositiveSmallIntegerField(blank=True, default=5, help_text='Percentage of Licenses that can be revoked for this SubscriptionPlan.'),
        ),
    ]
