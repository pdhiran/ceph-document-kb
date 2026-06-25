=========================
Installing with cephadm
=========================

``cephadm`` is the recommended tool for deploying and managing Ceph clusters.

Prerequisites
=============

- Python 3.6+
- Docker or Podman
- Network access between nodes

.. note:: Cephadm requires passwordless SSH between all nodes.

Bootstrap
=========

Bootstrap a new cluster:

.. code-block:: bash

   cephadm bootstrap --mon-ip <mon-ip>

This will:

1. Create a new cluster with a single monitor
2. Generate ``/etc/ceph/ceph.conf``
3. Deploy a manager daemon
4. Deploy a crash service

Adding Hosts
============

After bootstrap, add additional hosts:

.. code-block:: bash

   ceph orch host add <hostname> <ip-address>

.. code-block:: bash

   cephadm shell -- ceph orch host ls

Deploy OSDs
===========

Deploy OSDs on all available devices:

.. code-block:: bash

   ceph orch apply osd --all-available-devices

Or on specific devices:

.. code-block:: yaml

   service_type: osd
   service_id: default_drive_group
   placement:
     hosts:
       - ceph-node1
       - ceph-node2
   data_devices:
     paths:
       - /dev/sdb
       - /dev/sdc
