# Security policy

EdgeGuard is a safety system: a wrong or missing alert can hurt someone. Please report security problems privately.

## Reporting

Use GitHub's private vulnerability reporting: **Security → Report a vulnerability** on this repository. Include the component (firmware, MEC app, MEC-IPE, orchestrator, broker / CSE configuration), how to reproduce, and the impact you expect. We answer within 7 days during the hackathon period.

Do not open a public issue for a vulnerability. Problems in the CSE itself belong to its project (for ACME: [ankraft/ACME-oneM2M-CSE](https://github.com/ankraft/ACME-oneM2M-CSE)); tell us too if EdgeGuard's configuration makes them worse.

## What the design already covers

Described in [docs/transport-security.md](docs/transport-security.md) and checked in CI on every commit:

- devices authenticate with per-device certificates (site CA, CN = originator) over mutual TLS, with revocation (CRL) and rotation
- the broker ACL lets a device send requests only under its own originator
- apps and CSEs use HTTPS; plaintext HTTP and MQTT are refused
- one ACP per device AE; applications may only read and subscribe (accessControlObjectDetails)
- deployed app instances lose their device access when they are re-placed
- worker trajectories stay on the site's MEC host; federated learning shares weights only

## Out of scope for the demo setup

`scripts/certs.sh` creates demo keys and passwords on your machine. They are for local runs and CI, not for a real site. A deployment needs its own PKI, secret storage and network segmentation.
