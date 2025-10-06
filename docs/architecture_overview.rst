===========================================================================
License Manager Service - Architecture Overview
===========================================================================

:Author: Development Team
:Date: |today|
:Version: 1.0

.. contents:: Table of Contents
   :depth: 3

Introduction
============

The License Manager is a Django-based backend service that manages enterprise software licenses
and subscriptions within the Open edX ecosystem. This document provides an architectural overview
for development teams new to the edX platform.

What is Open edX?
=================

Open edX is an open-source platform for creating and delivering online courses. The
ecosystem consists of several interconnected services:

- **LMS (Learning Management System)**: Where learners take courses
- **Studio**: Course authoring tool for educators  
- **Enterprise**: B2B features for corporate customers
- **License Manager**: Manages enterprise licenses and subscriptions (this service)
- **Enterprise Catalog**: Manages course catalogs for enterprises

Service Purpose
===============

The License Manager handles:

- Enterprise customer license lifecycle management
- Subscription plan creation and renewal
- License assignment to learners
- References to billing/bookeeping system identifiers
- Automated license expiration and notifications

High-Level Architecture
======================

System Context Diagram
-----------------------

::

    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
    │   Enterprise    │    │ Enterprise      │    │ Enterprise      │
    │   Admins        │    │ Learners        |    | Catalog         |
    └─────────┬───────┘    └─────────┬───────┘    └─────────────────┘
              │                      │                      ▲
              │ Manage Licenses      │ Enroll in Courses    │ Content Catalog
              │                      │                      │ Validation
              ▼                      ▼                      │
    ┌─────────────────────────────────────────────────────────────────────┐
    │                    LICENSE MANAGER                                  │
    │                                                                     │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
    │  │     API     │  │Subscriptions│  │     Core    │  │ API Client  │ │
    │  │   (REST)    │  │   (Models)  │  │ (Auth/Base) │  │(Integrations) │
    │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │
    └─────────────────────────────────────────────────────────────────────┘
              │                      │                      │
              │ Customer Data        │ Email Notifications  │ Billing
              │                      │                      │
              ▼                      ▼                      ▼
    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
    │   Enterprise    │    │     Braze       │    │   Salesforce    │
    │   Service       │    │  (Marketing)    │    │  (Billing)      │
    └─────────────────┘    └─────────────────┘    └─────────────────┘

Application Architecture
========================

The License Manager follows Django's Model-View-Controller pattern with four main applications:

Application Structure
---------------------

::

    License Manager Service
    ├── API Layer (api/)
    │   ├── REST Endpoints (v1/views.py)
    │   ├── Serializers (serializers.py)
    │   ├── Permissions (permissions.py)
    │   └── Filtering (filters.py)
    │
    ├── Business Logic (subscriptions/)
    │   ├── Models (models.py)
    │   ├── Admin Interface (admin.py)
    │   ├── Background Tasks (tasks.py)
    │   └── Management Commands
    │
    ├── External Integrations (api_client/)
    │   ├── Enterprise Service Client
    │   ├── LMS Client
    │   ├── Braze Client (Email)
    │   └── Enterprise Catalog Client
    │
    └── Core Infrastructure (core/)
        ├── Base Models
        ├── Authentication
        └── Shared Utilities

Core Data Models
================

Entity Relationship Overview
----------------------------

::

    ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
    │CustomerAgreement│ 1:n  │ SubscriptionPlan│ 1:n  │    License      │
    │                 │─────▶│                 │─────▶│                 │
    │ - enterprise_id │      │ - start_date    │      │ - user_email    │
    │ - renewal_terms │      │ - end_date      │      │ - status        │
    │ - settings      │      │ - num_licenses  │      │ - assigned_date │
    └─────────────────┘      │ - product       │      │ - activated_date│
                             └─────────────────┘      └─────────────────┘
                                      │
                                      │ n:1
                                      ▼
                             ┌─────────────────┐
                             │    Product      │
                             │                 │
                             │ - name          │
                             │ - description   │
                             └─────────────────┘

Key Models Explained
--------------------

**CustomerAgreement**
  Represents an enterprise customer's contract terms and settings.
  Links to enterprise customer in the Enterprise service.

**SubscriptionPlan**  
  A specific subscription with licensing terms, dates, and allocated license count.
  Connected to a Product and CustomerAgreement.

**License**
  Individual license that can be assigned to learners.
  Tracks status lifecycle: ``unassigned → assigned → activated → revoked``

**Product**
  Defines what the subscription provides access to (courses, features).

**LicenseEvent**
  Historical audit trail of all license state changes.

License Lifecycle
=================

License State Machine
---------------------

::

    ┌─────────────┐   assign()   ┌─────────────┐  activate()  ┌─────────────┐
    │ UNASSIGNED  │─────────────▶│  ASSIGNED   │─────────────▶│  ACTIVATED  │
    └─────────────┘              └─────────────┘              └─────────────┘
           ▲                            │                            │
           │   reset_to_unassigned()    |  reset_to_unassigned()     │
           └────────────────────────────┘----------------------------| 
                                        │                            │
                                        │ revoke()                   │ revoke()
                                        ▼                            ▼
                                ┌─────────────┐              ┌─────────────┐
                                │   REVOKED   │              │   REVOKED   │
                                └─────────────┘              └─────────────┘

**States:**

- **UNASSIGNED**: License available for assignment
- **ASSIGNED**: License assigned to a learner but not yet activated  
- **ACTIVATED**: Learner has activated their license and can access content
- **REVOKED**: License has been revoked and cannot be used

API Architecture
================

RESTful API Design
------------------

The service exposes a versioned REST API (``/api/v1/``) with the following endpoint categories:

**Customer Management:**
  - ``/customer-agreements/`` - Enterprise customer contract management
  - ``/customer-agreements/{uuid}/auto-apply/`` - Auto-assign licenses

**Subscription Management:**
  - ``/subscriptions/`` - Subscription plan CRUD operations
  - ``/subscriptions/{uuid}/licenses/`` - License management per subscription

**License Operations:**
  - ``/licenses/`` - Individual license management
  - ``/licenses/assign/`` - Bulk license assignment
  - ``/licenses/revoke/`` - License revocation

**Authentication & Authorization**
  - JWT token-based authentication
  - Role-based access control (RBAC) with enterprise context
  - Permission levels: Admin, Learner, Support staff

Integration Architecture
========================

External Service Integration
----------------------------

::

    ┌─────────────────────────────────────────────────────────────────┐
    │                    LICENSE MANAGER                              │
    │                                                                 │
    │ ┌─────────────────────────────────────────────────────────────┐ │
    │ │                 API CLIENT LAYER                            │ │
    │ │                                                             │ │
    │ │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────┐│ │
    │ │  │ Enterprise  │ │     LMS     │ │    Braze    │ │Ent.Cat. ││ │
    │ │  │   Client    │ │   Client    │ │   Client    │ │ Client  ││ │
    │ │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────┘│ │
    │ └─────────────────────────────────────────────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
              │                 │                 │               │
              │                 │                 │               │
              ▼                 ▼                 ▼               ▼
    ┌─────────────────┐ ┌─────────────────┐ ┌─────────────┐ ┌─────────────┐
    │   Enterprise    │ │       LMS       │ │    Braze    │ │ Enterprise  │
    │ (LMS runtime)   │ │(edx-platfrom)   │ │             │ │  Catalog    │
    │                 │ │                 │ │             │ │             │
    │ • Customer Data │ │ • User Mgmt     │ │ • Email     │ │ • Course    │
    │ • Learner Info  │ │ • Enrollments   │ │   Campaigns │ │   Catalog   │
    │ • Enterprise    │ │ • Course Access │ │ • Analytics │ │ • Content   │
    │   Settings      │ │                 │ │             │ │   Metadata  │
    └─────────────────┘ └─────────────────┘ └─────────────┘ └─────────────┘

**Integration Purposes:**

**Enterprise/LMS Integration:**
  - Fetch enterprise customer information
  - Retrieve learner details and enterprise associations
  - Validate enterprise permissions and settings
  - Enroll learners in courses when licenses are activated

**Braze Integration:**
  - Send license assignment notifications
  - License activation reminders
  - Renewal and expiration alerts
  - Utilization reports to administrators

**Enterprise Catalog Integration:**
  - Validate content catalog inclusion for subscription plans and licenses
  - Retrieve course metadata and availability
  - Ensure licensed content matches catalog offerings

Background Processing
=====================

Asynchronous Task Architecture
------------------------------

::

    ┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
    │   Django App    │      │   Celery Queue  │      │ Celery Workers  │
    │                 │      │    (Redis)      │      │                 │
    │ • API Requests  │─────▶│                 │─────▶│ • Email Tasks   │
    │ • Admin Actions │      │ • Task Queue    │      │ • Renewal Jobs  │
    │ • Cron Jobs     │      │ • Task Results  │      │ • Bulk Ops      │
    └─────────────────┘      └─────────────────┘      └─────────────────┘

**Common Background Tasks:**

- **License Assignment Emails** - Notify learners of new licenses
- **Renewal Processing** - Automatic subscription renewals  
- **License Expiration** - Handle expired license cleanup
- **Bulk Operations** - Mass license assignment/revocation
- **Utilization Reports** - Generate usage analytics for customer admins

Management Commands
===================

Administrative Operations
-------------------------

The service includes Django management commands for operational tasks:

**Subscription Management:**
  - ``process_renewals`` - Handle subscription renewals
  - ``expire_subscriptions`` - Process expired subscriptions
  - ``process_auto_scalable_plans`` - Handle dynamic licensing

**License Operations:**
  - ``retire_old_licenses`` - Clean up historical license data
  - ``unlink_expired_licenses`` - Remove expired license associations

**Data Management:**
  - ``manufacture_data`` - Generate test data for development
  - ``seed_enterprise_devstack_data`` - Setup development environment

Deployment Architecture
=======================

Container and Service Deployment
---------------------------------

::

    ┌─────────────────────────────────────────────────────────────────┐
    │                        DOCKER ENVIRONMENT (local)               │
    │                                                                 │
    │ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐ │
    │ │  License Mgr    │ │     MySQL       │ │       Redis         │ │
    │ │   Container     │ │   Container     │ │     Container       │ │
    │ │                 │ │                 │ │                     │ │
    │ │ • Django App    │ │ • Database      │ │ • Celery Queue      │ │
    │ │ • Gunicorn      │ │ • Migrations    │ │ • Cache             │ │
    │ │ • Static Files  │ │ • Data Persist  │ │ • Session Store     │ │
    │ └─────────────────┘ └─────────────────┘ └─────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
    ┌─────────────────────────────────────────────────────────────────┐
    │                      EXTERNAL SERVICES                          │
    │                                                                 │
    │ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ │
    │ │ Enterprise  │ │     LMS     │ │   Braze     │ │ Salesforce  │ │
    │ │  Service    │ │             │ │             │ │             │ │
    │ └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘ │
    └─────────────────────────────────────────────────────────────────┘

Security Architecture
=====================

Security Measures
-----------------

**Authentication:**
  - JWT (JSON Web Token) based authentication
  - Integration with edX OAuth2 provider
  - Session-based authentication for admin interface

**Authorization:**
  - Role-based access control (RBAC)
  - Enterprise-scoped permissions
  - Multi-level access (Admin, Staff, Learner)

**Data Protection:**
  - PII (Personally Identifiable Information) annotations on models
  - Secure API endpoints with proper permission checks
  - Audit trail through history models and event tracking.

**API Security:**
  - Rate limiting and throttling
  - Input validation and sanitization
  - CSRF protection for web interfaces

Glossary
========

**Customer Agreement**
  Relationship between edX and an enterprise customer defining subscription terms over 1 or more plans.

**Enterprise Customer**
  Business organization purchasing licenses for their employees/learners

**License**
  Permission for a specific learner to access licensed content

**Subscription Plan**
  Time-bound allocation of licenses with specific terms and pricing

**Product**
  Defines what content/features are accessible with a license

**Auto-applied License**
  License automatically assigned when an eligible learner logs in

**Revocation**
  Process of removing a license from a learner, making it available for reassignment
