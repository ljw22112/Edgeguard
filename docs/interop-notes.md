# Interoperability test notes

[← README](../README.md) · [한국어](ko/interop-notes.md)

EdgeGuard connects to two oneM2M implementations (ACME CSE and KETI Mobius) with the same code, and we also tested registering the two CSEs with each other (Mcc).
This note records the issues found during testing and how we handled them.

## Test environment

| Component | Version / configuration |
|---|---|
| KETI Mobius | 3.0.1 (IN-CSE), MySQL backend (MariaDB 10.11), `cseId=/Mobius2`, `srv: 1, 2, 2a` |
| ACME CSE | 2026.05.1, MN-CSE mode (`cse-mn`, `/id-mn`), `releaseVersion=2a` |
| EdgeGuard client | `edgeguard/onem2m.py`, HTTP binding, JSON |

## Summary of results

| Item | Result |
|---|---|
| EdgeGuard → ACME (IN, RVI 3) full loop | ✅ |
| EdgeGuard → Mobius (IN, RVI 2a) full loop | ✅ Configuration change only, no code changes |
| ACME MN-CSE → Mobius IN-CSE CSR registration | ✅ (requires MySQL backend) |
| CIN created in the cloud via ACME MN retargeting (`~/Mobius2/Mobius/...`) | ✅ |

## Issues found

### 1. ACME fails to parse the Content-Type of Mobius responses (fixed on the ACME side)

- Symptom: ACME MN cannot process responses to its requests to Mobius, so registration fails.
- Cause: Mobius responds with `Content-Type: application/json; charset=utf-8`, but ACME's `HttpServer.sendHttpRequest()`
  uses the raw header value to look up the serialization type, so the `; charset=utf-8` part prevents it from being recognised as JSON.
- Fix (ACME `acmecse/plugins/bindings/HttpServer.py`):
  ```python
  resp.ct = ContentSerializationType.getType(r.headers.get('Content-Type', ct).split(';')[0].strip())
  ```
  Strips media-type parameters before comparing (patch: [acme-content-type.patch](acme-content-type.patch)). Parameters are allowed by the HTTP standard, so this is a bug to report to ACME.

### 2. Mobius SQLite backend does not support remoteCSE

- Mobius 3's SQLite backend supports only CSEBase, AE, ACP, container, contentInstance and subscription,
  and rejects everything else (including remoteCSE) with `501 / RSC 5001`. Mcc registration testing requires the MySQL backend.
- Importing `mobiusdb.sql` into MariaDB fails because the `utf8mb4_0900_ai_ci` collation is missing,
  so we imported it after replacing it with `utf8mb4_general_ci` (and `utf8mb4_0900_bin` → `utf8mb4_bin`).

### 3. Intermittent 404/409 when recreating an AE with the same name right after deleting it on Mobius

- Symptom: after deleting an AE and immediately recreating it, creating its child containers fails with a name conflict (409) or path not found (404).
- Suspected cause: propagation delay between cluster workers and the timing of child-resource cleanup.
- Mitigation (`tools/setup_resources.py`, `edgeguard/onem2m.py`): on reset, delete child resources first;
  retry creation briefly on 404; for existing subscriptions, update only `nu` (PUT).

### 4. MN-CSE retargeting goes directly to the poa received at registration (test environment only)

- After registration, ACME MN sends retargeted requests to the poa (host IP) advertised by Mobius.
  When emulating WAN latency on a single PC, this path bypasses the latency proxy,
  so the test script rewrites the MN's CSR `poa` to the proxy address (`pin_registrar_poa` in `tools/topology_bench.py`).
  In a real deployment that address is itself across the WAN, so this does not apply.

### 5. Supported release version mismatch

- The Mobius 3 CSEBase supports `srv: ["1","2","2a"]`; ACME supports `2a, 3, 4, 5`.
  Aligning on the common denominator `2a` works on both (`rvi: "2a"` in `config/site.yaml`).

### 6. Mobius allows one AE per originator

- Creating another AE with a different name using the same `X-M2M-Origin` returns 409 (conflict), and that path then appears as 404.
  This is because the AE-ID is derived from the originator. When creating a separate AE for testing, use a separate originator as well.

### 7. acpi reference format for Mobius ACPs

- Putting a structured path (`Mobius/EdgeGuard/acp_worker_01`) in `acpi` works, and Mobius returns it in the form `/Mobius/...`.
  `set_acpi` in `edgeguard/onem2m.py` tries the structured path first and, if that fails, retries with the resource ID.
