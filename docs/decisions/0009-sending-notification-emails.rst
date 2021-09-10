9. Sending Notification Emails
======================

Status
======

Accepted September 2021

Context
=======

As part of the the `auto-assign subscription licenses epic <https://openedx.atlassian.net/browse/ENT-4852>`_, we want to send email notifications 
to admins to provide visibility into the license allocation rate. An email will be sent
1. Once when 75% of the licenses of the subscription plan used for auto-assign (active plan expiring soonest) have been allocated (assigned + activated)
2. Once when 100% of the licenses have been allocated
3. Weekly after the 7th day the admin has activated their account

Defintions
----------
* **Segment** The customer data platform that we use to create our data pipeline

* **Segment Personas** Segment product that allows us to create profiles for users based on event and external data

* **Personas SQL Traits** SQL Traits allow us to import user data from Snowflake into Segment through SQL queries that are executed every 12 hours.
    Data can be pushed to Braze and used as `custom attributes <https://www.braze.com/docs/user_guide/data_and_analytics/custom_data/custom_attributes/>`_
    to filter and segment users. You can see all of the custom attributes `here <https://dashboard-06.braze.com/app_settings/app_settings/custom_attributes/>`_

* **Braze** The Email Service Provider that we use to send user communications (Email, Push Notification, etc.).
    Braze hosts templates for messages and allow marketing content to be edited independently by the marketing team. 
    The Braze dashboard can be accessed `here <https://dashboard-06.braze.com/>`_

Decision
========

After exploring the feasibility of using SQL Traits/Braze to handle the logic for sending emails, we have decided to go with our initial approach of using a cron job
to trigger email notifications.

The Braze messaging API provides an endpoint ``POST /campaigns/trigger/send`` which can be called to send campaign messages.
Refer to the `documentation <https://www.braze.com/docs/api/endpoints/messaging/send_messages/post_send_triggered_campaigns/>`_ for more details. 
There is another endpoint ``POST /messages/send`` which takes a message in the payload but the first one will allow us to keep the email template within Braze.

A cron job will run daily to execute the management command `send_license_consumption_notifications` to trigger notifications.
The command will fetch all enterprises with auto-assign licenses turned on, and query LMS for all of the associated admin users. 
The Braze API will be called for each of the conditions met, i.e. an admin can receive the weekly email as well as the 75% utilized email at the same time.
Note that a separate ```EnterpriseCustomerUser``` is created for each enterprise a user is associated with. A user that's an admin of multiple enterprises can receive multiple emails.
A new model will be created to store the last time an admin recevied a email for both utilization and weekly digest.
If an error occurs during the command, we will trigger a notification with information on which enterprise customer and/or admin the error occured for. 
An error should not stop the command and failure to send an email should not stop the rest of the emails from being sent.  

The payload for the call to Braze might look like
```
{
  "campaign_id": "campaign_id",
  "trigger_properties": {
    "enterprise_customer_id": "enterprise_customer_id",
    "subscription_plan_uuid" : "subscription_plan_uuid",
    "allocated_license_count" : 8,
    "total_license_count": 10
  }
  "recipients":
    [{
      "external_user_id": "enterprise_admin_user_id_1",
      "trigger_properties": {
        "user_name": "enterprise_admin_user_1"
        ...
      }
    },
    {
      "external_user_id": "admin_user_id_2",
       "trigger_properties": {
        "user_name": "enterprise_admin_user_2"
        ...
      }
    }]
}
```

The `trigger_properties` in the payload can be used in the email template to personalize emails for each admin. 
Braze has a concept of the `re-eligibility window <https://www.braze.com/docs/user_guide/engagement_tools/campaigns/scheduling_and_organizing/delivery_types/api_triggered_delivery/#re-eligibility-with-api-triggered-campaigns>`_ for campaigns. 
A user who has received a campaign will not receive it again unless specified so we need to configure the re-eligibility window to ensure that users can receive weekly emails.

Alternatives Considered
=======================

SQL Traits Approach
-------------------
We explored an alternative approach where we use SQL traits and Braze to drive the notifications, possibly eliminating the need of a cron job.
To support the notifications that we will send, we would compute SQL traits which can be used to target admin users in Braze.
* is_enterprise_admin - determines whether a user is an enterprise admin 
* activation_date - date when the admin was activated 
* allocated_license_count - number of allocated licenses 
* total_license_count - total number of licenses 
* license_allocation_percentage - allocated_license_count / total_license_count

We can then use these custom traits to create two segments of users in Braze using filters.
1. Enterprise admin users with an activation_date more than 7 days ago
2. Enterprise admin users with license_allocation_percentage more than 75

We would need BI support to create a DBT model in the segment_personas schema in Snowflake. Refer to https://openedx.atlassian.net/wiki/spaces/DE/pages/2689630579/Segment+Personas+Usage for more information.

In order for this approach to work we would have to make the following assumptions
1. Only one plan is used for auto-assign
2. An admin only belongs to one enteprise

Issues arise when those assumptions don't hold true since we cannot use single value fields. We could add additional fields for each enterprise, but that doens't scale and it's not possible to segment users based on a attribute that is not predefined. 
Factoring in multiple enterprises and subscriptions introduces more overhead and headache, hence the initial approach is a better fit.

Using JWT Roles to Determine Admin Role
---------------------------------------
A authentication user is created in `license-manager` which might be used as proxy to check wheter a user is an admin or not if we extract the JWT roles.
This method removes the need to query LMS but it relies on the user calling `license-manager` at least once.

Consequences
============

* Every admin part of an enterprise with auto-assign licenses turned on will receive notification emails. If we want to control which admins receive notifications,
  we would need additional implementations.