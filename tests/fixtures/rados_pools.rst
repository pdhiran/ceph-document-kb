.. _pools:

=====
Pools
=====

A pool is a logical partition for storing objects.

.. note:: Most Ceph deployments use replicated pools.

Pool Operations
===============

Creating a Pool
---------------

To create a pool, execute::

   ceph osd pool create {pool-name} [{pg-num} [{pgp-num}]]

For example:

.. code-block:: bash

   ceph osd pool create mypool 128 128

.. warning:: Do not set the pg_num value to a number that is not a power of two.

.. versionadded:: 14.0

Setting Pool Quotas
-------------------

You can set pool quotas for the maximum number of bytes and/or the maximum
number of objects per pool:

.. code-block:: bash

   ceph osd pool set-quota {pool-name} [max_objects {obj-count}] [max_bytes {bytes}]

For example:

.. code-block:: bash

   ceph osd pool set-quota mypool max_objects 10000

To remove a quota, set its value to ``0``.

Erasure Coding
==============

Erasure coded pools require less storage space compared to replicated pools.

.. seealso:: `Erasure Code <../erasure-code>`_ for more details.

Creating an Erasure Coded Pool
------------------------------

To create an erasure coded pool:

.. code-block:: bash

   ceph osd pool create {pool-name} erasure [{erasure-code-profile}]

.. deprecated:: 18.0
   The ``crush_ruleset`` parameter is deprecated. Use ``crush_rule`` instead.

.. code-block:: json

   {
     "pool": "ecpool",
     "type": "erasure",
     "k": 2,
     "m": 1
   }
