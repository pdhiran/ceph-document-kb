===============
RBD Mirroring
===============

.. index:: Ceph Block Device; mirroring

RBD mirroring allows you to replicate RBD images between two Ceph clusters.

.. versionadded:: 10.2

Enable Mirroring
================

To enable mirroring on a pool:

.. code-block:: bash

   rbd mirror pool enable {pool-name} {mode}

Where ``{mode}`` is either ``pool`` or ``image``.

For example:

.. code-block:: bash

   rbd mirror pool enable rbd-pool image

.. important:: Ensure the cluster is healthy before enabling mirroring.

Image Mirroring
===============

Enable mirroring on a specific image:

.. code-block:: bash

   rbd mirror image enable {pool-name}/{image-name}

.. versionchanged:: 14.0
   Added support for snapshot-based mirroring mode.

Status
------

Check mirroring status:

.. code-block:: bash

   rbd mirror pool status rbd-pool
   rbd mirror image status rbd-pool/myimage
