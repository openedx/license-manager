5. Freezing unused licenses on a subscription plan
======================

Status
======

Accepted August 2021

Context
=======

Most use cases for ``license-manager`` to date have been for billing proactively, where a set of licenses
(subscription plan) is purchased per seat as a pre-sale versus being billed retroactively based on utilization
of those licenses. For example, if a customer signs up for a subscription plan with 100 licenses, typically the
quote would be per-seat, paying for each individual license regardless of whether it is utilized by an administrator.

The decision below describes a configurable flag to toggle whether a subscription plan may be "frozen" to delete unused
licenses to accomodate a usage-based payment plan for a subscription customer. This allows us to assess how many licenses
were used in a quarter and ensure additional licenses are not picked up from previous quarters.

Decision
========

To support such a retroactive billing option, we will add boolean flag to enable the new, optional billing feature for
a given Subscription Plan. We will also introduce a Django action that allows "freezing" selected subscription plans to delete
unused licenses (i.e., unassigned) from the subscription plan.

By supporting the deletion of unused licenses, it allows staff to capture at the end of each quarter how many licenses were
allocated, including both activated and assigned licenses. Activated licenses are included as they have been utilized by a
learner and may have course enrollments associated with the license. Assigned licenses are included as they have the potential
to be utilized, or activated, at a later date by a learner as license activation and/or reminder emails were already sent.

The timestamp at which a given subscription plan is frozen will be captured for historical purposes. Related, the existence of
the now-deleted, unassigned licenses can be determined via the history tables for licenses and their associated subscription plans.

Consequences
============

* We assume usage-based billing should be for allocated licenses (activated + assigned) as opposed to just activated, as there
  is no configurable way to change which licenses are deleted from a "frozen" subscription plan as it solely deletes unassigned
  licenses.
* Related, our definiton of a "used" license solely means it was activated by a learner; it does not indicate the license was used
  to enroll in one or more courses in the assciated subscription catalog.
* After freezing a subscription plan, unassigned licenses are deleted with no way to manually "undo" the freeze action.

Alternatives Considered
=======================

The decision described above is not intended to make subscription plans support many flexible billing options. Rather, it is intended
to provide short-term flexibility while we evaluate our long-term strategy to support more automation around billing. Other considerations
are described below.

* **Allow staff to manually change the number of seats in an existing subscription plan.** We opted to avoid this approach to reduce the
  chance for manual error that some slight automation can provide simply by clicking a button in the Django admin UI.
