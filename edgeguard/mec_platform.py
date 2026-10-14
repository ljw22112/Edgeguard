"""ETSI MEC platform APIs a MEC app instance uses besides Location and RNIS:

* MEC 011 (Mp1): confirm the instance is ready, register its own service so other MEC apps can find it,
  discover the platform's services (e.g. the Location service) and follow their availability;
* MEC 021 Application Mobility Service: register the UEs the instance serves, get notified when one moves
  to another MEC host (with the target instance), transfer that UE's context, report the transfer done.

EdgeGuard registers its service with a pointer to its oneM2M AE, so a MEC app that only knows Mp1 finds the
oneM2M resources; and AMS becomes a handover trigger authority for the oneM2M twin (tools/mec_platform_demo.py).
"""
from __future__ import annotations

import requests


class Mp1Client:
    def __init__(self, base, app_instance_id, timeout=3.0):
        self.base, self.app, self.t = base.rstrip("/"), app_instance_id, timeout
        self.services: dict[str, str] = {}

    def confirm_ready(self):
        r = requests.post(f"{self.base}/mec_app_support/v2/applications/{self.app}/confirm_ready",
                          json={"indication": "READY"}, timeout=self.t)
        r.raise_for_status()

    def register_service(self, name, uri, category="EdgeGuard", version="1.5", onem2m=None):
        """ServiceInfo with a REST transport whose endpoint is the service URI; `onem2m` (CSE base + AE path)
        tells oneM2M-aware consumers where the resources are."""
        info = {"serName": name, "serCategory": {"href": "", "id": category.lower(), "name": category, "version": version},
                "version": version, "state": "ACTIVE",
                "transportInfo": {"id": f"{name}-rest", "name": "REST", "type": "REST_HTTP", "protocol": "HTTP",
                                  "version": "1.1", "endpoint": {"uris": [uri]}},
                "serializer": "JSON", "scopeOfLocality": "MEC_HOST", "consumedLocalOnly": True, "isLocal": True}
        if onem2m:
            info["transportInfo"]["implSpecificInfo"] = {"oneM2M": onem2m}
        r = requests.post(f"{self.base}/mec_service_mgmt/v1/applications/{self.app}/services", json=info, timeout=self.t)
        r.raise_for_status()
        sid = r.json()["serInstanceId"]
        self.services[name] = sid
        return sid

    def deregister_service(self, name):
        sid = self.services.pop(name, None)
        if sid:
            requests.delete(f"{self.base}/mec_service_mgmt/v1/applications/{self.app}/services/{sid}", timeout=self.t)

    def discover(self, name):
        r = requests.get(f"{self.base}/mec_service_mgmt/v1/services", params={"ser_name": name}, timeout=self.t)
        r.raise_for_status()
        return r.json()

    def endpoint(self, name):
        """URI of the first service called `name` (e.g. the platform's Location service)."""
        found = self.discover(name)
        return ((found[0].get("transportInfo") or {}).get("endpoint") or {}).get("uris", [None])[0] if found else None

    def subscribe_availability(self, callback, names=None):
        body = {"subscriptionType": "SerAvailabilityNotificationSubscription", "callbackReference": callback,
                "filteringCriteria": {"serNames": list(names or [])}}
        r = requests.post(f"{self.base}/mec_service_mgmt/v1/applications/{self.app}/subscriptions", json=body, timeout=self.t)
        r.raise_for_status()
        return r.json()


class AmsClient:
    def __init__(self, base, app_instance_id, mec_host, timeout=3.0):
        self.base, self.app, self.host, self.t = base.rstrip("/"), app_instance_id, mec_host, timeout
        self.reg_id = None
        self.reg: dict = {}

    def register(self, ues, comm=None):
        """The UEs this instance serves, with context transfer; `comm` = where a source instance sends context."""
        self.reg = {"serviceConsumerId": {"appInstanceId": self.app, "mecHost": self.host},
                    "deviceInformation": [{"associateId": {"type": "UE_IPv4_ADDRESS", "value": u},
                                           "appMobilityServiceLevel": "APP_MOBILITY_PERMITTED_WITH_CONTEXT_TRANSFER",
                                           "contextTransferState": "NOT_TRANSFERRED"} for u in ues]}
        if comm:
            self.reg["commInterface"] = {"ipAddresses": [{"host": comm[0], "port": comm[1]}]}
        r = requests.post(f"{self.base}/amsi/v1/app_mobility_services", json=self.reg, timeout=self.t)
        r.raise_for_status()
        self.reg_id = r.json()["appMobilityServiceId"]
        return self.reg_id

    def subscribe(self, callback, statuses=("INTERHOST_MOVEOUT_TRIGGERED", "INTERHOST_MOVEOUT_COMPLETED")):
        body = {"subscriptionType": "MobilityProcedureSubscription", "callbackReference": callback,
                "filterCriteria": {"appInstanceId": self.app, "mobilityStatus": list(statuses)}}
        r = requests.post(f"{self.base}/amsi/v1/subscriptions", json=body, timeout=self.t)
        r.raise_for_status()
        href = ((r.json().get("_links") or {}).get("self") or {}).get("href", "")
        return href

    def context_transferred(self, ue):
        for d in self.reg.get("deviceInformation", []):
            if d["associateId"]["value"] == ue:
                d["contextTransferState"] = "USER_CONTEXT_TRANSFER_COMPLETED"
        r = requests.put(f"{self.base}/amsi/v1/app_mobility_services/{self.reg_id}",
                         json={"deviceInformation": [d for d in self.reg["deviceInformation"] if d["associateId"]["value"] == ue]},
                         timeout=self.t)
        r.raise_for_status()
