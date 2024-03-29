# Generated by Django 2.2.23 on 2021-06-02 21:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0024_auto_20210528_1953'),
    ]

    operations = [
        migrations.AddField(
            model_name='historicalsubscriptionplanrenewal',
            name='license_types_to_copy',
            field=models.CharField(choices=[('assigned_and_activated', 'Assigned and activated'), ('activated', 'Activated'), ('nothing', 'None')], default='assigned_and_activated', help_text="Which types of licenses are copied from the original plan to the future plan. 'None' means the future plan will be created with only unassigned licenses.", max_length=32),
        ),
        migrations.AddField(
            model_name='historicalsubscriptionplanrenewal',
            name='processed_datetime',
            field=models.DateTimeField(blank=True, help_text='The time at which the renewal was processed.', null=True),
        ),
        migrations.AddField(
            model_name='historicalsubscriptionplanrenewal',
            name='renewed_plan_title',
            field=models.CharField(blank=True, help_text='The title of the future plan.', max_length=128, null=True),
        ),
        migrations.AddField(
            model_name='subscriptionplanrenewal',
            name='license_types_to_copy',
            field=models.CharField(choices=[('assigned_and_activated', 'Assigned and activated'), ('activated', 'Activated'), ('nothing', 'None')], default='assigned_and_activated', help_text="Which types of licenses are copied from the original plan to the future plan. 'None' means the future plan will be created with only unassigned licenses.", max_length=32),
        ),
        migrations.AddField(
            model_name='subscriptionplanrenewal',
            name='processed_datetime',
            field=models.DateTimeField(blank=True, help_text='The time at which the renewal was processed.', null=True),
        ),
        migrations.AddField(
            model_name='subscriptionplanrenewal',
            name='renewed_plan_title',
            field=models.CharField(blank=True, help_text='The title of the future plan.', max_length=128, null=True),
        ),
        migrations.AlterField(
            model_name='historicallicense',
            name='status',
            field=models.CharField(choices=[('activated', 'Activated'), ('assigned', 'Assigned'), ('unassigned', 'Unassigned'), ('revoked', 'Revoked'), ('transferred-renewal', 'Transferred for renewal')], default='unassigned', help_text="The status fields has the following options and definitions:\nActive: A license which has been created, assigned to a learner, and the learner has activated the license. The license also must not have expired.\nAssigned: A license which has been created and assigned to a learner, but which has not yet been activated by that learner.\nUnassigned: A license which has been created but does not have a learner assigned to it.\nRevoked: A license which has been created but is no longer active (intentionally revoked or has expired). A license in this state may or may not have a learner assigned.\nTransferred for renwal: The license's subscription plan was renewed into a new plan, and the license transferred to a new, active license in the renewed plan.", max_length=25),
        ),
        migrations.AlterField(
            model_name='license',
            name='status',
            field=models.CharField(choices=[('activated', 'Activated'), ('assigned', 'Assigned'), ('unassigned', 'Unassigned'), ('revoked', 'Revoked'), ('transferred-renewal', 'Transferred for renewal')], default='unassigned', help_text="The status fields has the following options and definitions:\nActive: A license which has been created, assigned to a learner, and the learner has activated the license. The license also must not have expired.\nAssigned: A license which has been created and assigned to a learner, but which has not yet been activated by that learner.\nUnassigned: A license which has been created but does not have a learner assigned to it.\nRevoked: A license which has been created but is no longer active (intentionally revoked or has expired). A license in this state may or may not have a learner assigned.\nTransferred for renwal: The license's subscription plan was renewed into a new plan, and the license transferred to a new, active license in the renewed plan.", max_length=25),
        ),
    ]
