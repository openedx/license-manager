# Generated by Django 2.2.19 on 2021-05-28 19:53

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0023_auto_20210527_1848'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalsubscriptionplan',
            name='plan_type',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='+', to='subscriptions.PlanType'),
        ),
        migrations.AddField(
            model_name='subscriptionplan',
            name='plan_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='subscriptions.PlanType'),
        ),
    ]
