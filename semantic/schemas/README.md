# Apache Ossie schema location

The project no longer keeps a duplicate schema in this directory. The authoritative offline
contract is `ossie-main/core-spec/osi-schema.json` from the Apache Ossie Git submodule, pinned to
commit `5c8a2a5f7e09e046e2055e5759e7df4a928b7a88`.

Initialize it with `git submodule update --init --recursive`. Upgrades require an explicit
submodule commit change, schema/hash review, regenerated fixtures, and the complete test suite.
