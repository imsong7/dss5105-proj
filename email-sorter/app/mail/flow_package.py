"""Build a ready-to-import Power Automate flow for one account.

The package is the same shape Power Automate exports ("Export > Package
(.zip)"): a root manifest, a flows manifest and one flow folder. It holds a
flow that, when its HTTP trigger is called, reads recent Outlook mail and
POSTs each email to this app's webhook.

Nothing in here comes from anyone's real export. The webhook address, email
and token are filled in per account, so every student downloads a flow that
only works for their own account. The Outlook connection is left for the
student to pick during import.
"""

from __future__ import annotations

import io
import json
import zipfile

# Fixed ids only link the parts of the package together; Power Automate gives
# the imported flow and connection new ids of its own.
FLOW_RESOURCE = "0f7e8a52-5b1c-4a0e-9c3d-2d6f1a7b9e10"
API_RESOURCE = "4b2c9d1e-7a3f-4e85-b6c0-8f1d2e3a4b51"
CONNECTION_RESOURCE = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c62"
FLOW_NAME = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"

DISPLAY_NAME = "Inbox sorter"
GET_EMAILS = "Get_emails_(V3)"
EACH_EMAIL = "Send_each_email"
INLINE_IMAGES = "Inline_images"
IMAGE_MAX_BYTES = 500_000  # per image: small requests keep each push fast and reliable
IMAGE_COUNT = 1            # one image per email is enough for a poster
TOP = 300  # emails read per refresh, split across the batches (the app may override it)
# Outlook reads ~0.18 s per email, so one big Get emails call is slow. With BATCHES > 1
# the window is cut into BATCHES date slices read in parallel (BATCHES = 1: one call).
# A slice returns at most TOP / BATCHES emails, so a busier slice loses its oldest.
BATCHES = 3
WINDOW_SINCE = "Window_start"
WINDOW_BEFORE = "Window_end"
BATCH_DAYS = "Days_per_batch"
EACH_BATCH = "Each_batch"
REFRESH_DONE = "Refresh_done"
# Sending poster images makes every email slow and heavy (the flow downloads each
# attachment and uploads up to IMAGE_COUNT images), so the count and size above are
# kept small. Set False for the fastest load; poster/OCR reading is then skipped.
INCLUDE_IMAGES = False  # False = fast text-only load; True = also read poster images
FOREACH_PARALLEL = None  # 1 to 50 parallel pushes per batch; None = Power Automate's default
DEFAULT_DAYS = 90


def _flat_definition(endpoint: str, email: str, token: str) -> dict:
    # The app sends {"owner", "since", "before"} when it asks for a refresh.
    # "since" picks how far back to read; with no body it reads DEFAULT_DAYS days.
    since = (
        "@concat('received>=', formatDateTime(coalesce(triggerBody()?['since'], "
        f"addDays(utcNow(), -{DEFAULT_DAYS})), 'yyyy-MM-dd'))"
    )
    return {
        "name": FLOW_NAME,
        "id": f"/providers/Microsoft.Flow/flows/{FLOW_NAME}",
        "type": "Microsoft.Flow/flows",
        "properties": {
            "apiId": "/providers/Microsoft.PowerApps/apis/shared_logicflows",
            "displayName": DISPLAY_NAME,
            "definition": {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {
                    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                    "$connections": {"defaultValue": {}, "type": "Object"},
                },
                "triggers": {
                    "manual": {
                        "metadata": {},
                        "type": "Request",
                        "kind": "Http",
                        "inputs": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "owner": {"type": "string"},
                                    "since": {"type": "string"},
                                    "before": {"type": "string"},
                                    "top": {"type": "integer"},
                                },
                            },
                            "triggerAuthenticationType": "All",
                        },
                    }
                },
                "actions": {
                    GET_EMAILS: {
                        "runAfter": {},
                        "type": "OpenApiConnection",
                        "inputs": {
                            "parameters": {
                                "importance": "Any",
                                "fetchOnlyWithAttachment": False,
                                "folderPath": "Inbox",
                                "fetchOnlyUnread": False,
                                # Images are needed to read posters; the step
                                # below keeps only small images, so the push
                                # stays under the server's request limit.
                                "includeAttachments": INCLUDE_IMAGES,
                                "searchQuery": since,
                                # The app may send "top" with a refresh; otherwise TOP is used.
                                "top": f"@coalesce(triggerBody()?['top'], {TOP})",
                            },
                            "host": {
                                "apiId": "/providers/Microsoft.PowerApps/apis/shared_office365",
                                "connectionName": "shared_office365",
                                "operationId": "GetEmailsV3",
                            },
                            "authentication": "@parameters('$authentication')",
                        },
                    },
                    EACH_EMAIL: {
                        "foreach": f"@outputs('{GET_EMAILS}')?['body/value']",
                        "actions": {
                            **({INLINE_IMAGES: {
                                "type": "Query",
                                "inputs": {
                                    "from": f"@coalesce(items('{EACH_EMAIL}')?['attachments'], json('[]'))",
                                    "where": (
                                        "@and(startsWith(toLower(coalesce(item()?['contentType'], '')), 'image/'), "
                                        f"less(int(coalesce(item()?['size'], 0)), {IMAGE_MAX_BYTES}))"
                                    ),
                                },
                                "runAfter": {},
                            }} if INCLUDE_IMAGES else {}),
                            "HTTP": {
                                **({"runAfter": {INLINE_IMAGES: ["Succeeded"]}} if INCLUDE_IMAGES else {}),
                                "type": "Http",
                                "inputs": {
                                    "uri": endpoint,
                                    "method": "POST",
                                    "headers": {
                                        "Content-Type": "application/json",
                                        "X-Webhook-Token": token,
                                        "X-User-Email": email,
                                        "ngrok-skip-browser-warning": "true",
                                    },
                                    "body": {
                                        "internetMessageId": "@{item()?['internetMessageId']}",
                                        "subject": "@{item()?['subject']}",
                                        "from": "@{item()?['from']}",
                                        "receivedDateTime": "@{item()?['receivedDateTime']}",
                                        "bodyPreview": "@{item()?['bodyPreview']}",
                                        "body": "@{item()?['body']}",
                                        # Up to 3 poster-sized images (base64), read on the server.
                                        **(
                                            {"inlineImages": f"@take(body('{INLINE_IMAGES}'), {IMAGE_COUNT})"}
                                            if INCLUDE_IMAGES
                                            else {}
                                        ),
                                    },
                                },
                                "runtimeConfiguration": {
                                    "contentTransfer": {"transferMode": "Chunked"}
                                },
                            }
                        },
                        "runAfter": {GET_EMAILS: ["Succeeded"]},
                        "type": "Foreach",
                        # Optional: push several emails at once. None keeps Power Automate's default.
                        **(
                            {"runtimeConfiguration": {"concurrency": {"repetitions": FOREACH_PARALLEL}}}
                            if FOREACH_PARALLEL
                            else {}
                        ),
                    },
                },
                "outputs": {},
            },
            "connectionReferences": {
                "shared_office365": {
                    "connectionName": "shared-office365",
                    "source": "Embedded",
                    "id": "/providers/Microsoft.PowerApps/apis/shared_office365",
                    "tier": "NotSpecified",
                    "apiName": "office365",
                }
            },
            "flowFailureAlertSubscribed": False,
            "isManaged": False,
        },
    }


def _manifest() -> dict:
    icon = "https://static.powerapps.com/resource/ppcr/releases/v1.0.1831/1.0.1831.5113/office365/icon.png"
    return {
        "schema": "1.0",
        "details": {
            "displayName": DISPLAY_NAME,
            "description": "Sends your recent Outlook mail to Inbox sorter when the app asks.",
            "createdTime": "2026-11-07T00:00:00Z",
            "packageTelemetryId": "",
            "creator": "Inbox sorter",
            "sourceEnvironment": "",
        },
        "resources": {
            FLOW_RESOURCE: {
                "type": "Microsoft.Flow/flows",
                "suggestedCreationType": "New",
                "creationType": "Existing, New, Update",
                "details": {"displayName": DISPLAY_NAME},
                "configurableBy": "User",
                "hierarchy": "Root",
                "dependsOn": [API_RESOURCE, CONNECTION_RESOURCE],
            },
            API_RESOURCE: {
                "id": "/providers/Microsoft.PowerApps/apis/shared_office365",
                "name": "shared_office365",
                "type": "Microsoft.PowerApps/apis",
                "suggestedCreationType": "Existing",
                "details": {"displayName": "Office 365 Outlook", "iconUri": icon},
                "configurableBy": "System",
                "hierarchy": "Child",
                "dependsOn": [],
            },
            CONNECTION_RESOURCE: {
                "type": "Microsoft.PowerApps/apis/connections",
                "suggestedCreationType": "Existing",
                "creationType": "Existing",
                "details": {"displayName": "Your Outlook connection", "iconUri": icon},
                "configurableBy": "User",
                "hierarchy": "Child",
                "dependsOn": [API_RESOURCE],
            },
        },
    }


def build_flow_package(endpoint: str, email: str, token: str) -> bytes:
    """Return the import package (.zip bytes) for one account."""
    folder = f"Microsoft.Flow/flows/{FLOW_RESOURCE}"
    files = {
        "manifest.json": _manifest(),
        "Microsoft.Flow/flows/manifest.json": {
            "packageSchemaVersion": "1.0",
            "flowAssets": {"assetPaths": [FLOW_RESOURCE]},
        },
        f"{folder}/apisMap.json": {"shared_office365": API_RESOURCE},
        f"{folder}/connectionsMap.json": {"shared_office365": CONNECTION_RESOURCE},
        f"{folder}/definition.json": _definition(endpoint, email, token),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, json.dumps(content, ensure_ascii=False))
    return buffer.getvalue()


def _definition(endpoint: str, email: str, token: str) -> dict:
    """The flow plus its last step, which tells the app the refresh finished."""
    flow = _sliced_definition(endpoint, email, token)
    actions = flow["properties"]["definition"]["actions"]
    last = EACH_BATCH if BATCHES > 1 else EACH_EMAIL
    actions[REFRESH_DONE] = {
        # Only after every step succeeded, so a half-finished run is never counted as synced.
        "runAfter": {last: ["Succeeded"]},
        "type": "Http",
        "inputs": {
            "uri": endpoint.rsplit("/", 1)[0] + "/refresh-done",
            "method": "POST",
            "headers": {
                "Content-Type": "application/json",
                "X-Webhook-Token": token,
                "X-User-Email": email,
                "ngrok-skip-browser-warning": "true",
            },
            "body": {},
        },
    }
    return flow


def _sliced_definition(endpoint: str, email: str, token: str) -> dict:
    """The main flow: one Get emails call, or BATCHES date slices read in parallel."""
    flow = _flat_definition(endpoint, email, token)
    if BATCHES <= 1:
        return flow

    definition = flow["properties"]["definition"]
    inner = definition["actions"]
    since_param = "coalesce(triggerBody()?['since'], addDays(utcNow(), -%d))" % DEFAULT_DAYS
    before_param = "coalesce(triggerBody()?['before'], utcNow())"
    # Whole days per batch, rounded up so the slices always cover the window.
    batch_days = (
        f"@max(1, div(add(div(sub(ticks(outputs('{WINDOW_BEFORE}')), ticks(outputs('{WINDOW_SINCE}'))), "
        f"864000000000), {BATCHES - 1}), {BATCHES}))"
    )
    n = f"items('{EACH_BATCH}')"
    days = f"outputs('{BATCH_DAYS}')"
    end = f"outputs('{WINDOW_BEFORE}')"
    # Slice n covers [lo, hi) by date; slice 0 is the newest, the last reaches back to "since".
    hi = f"formatDateTime(addDays({end}, sub(1, mul({n}, {days}))), 'yyyy-MM-dd')"
    lo = (
        f"formatDateTime(if(equals({n}, {BATCHES - 1}), outputs('{WINDOW_SINCE}'), "
        f"addDays({end}, sub(1, mul(add({n}, 1), {days})))), 'yyyy-MM-dd')"
    )
    params = inner[GET_EMAILS]["inputs"]["parameters"]
    params["searchQuery"] = f"@concat('received>=', {lo}, ' AND received<', {hi})"
    params["top"] = f"@div(coalesce(triggerBody()?['top'], {TOP}), {BATCHES})"

    definition["actions"] = {
        WINDOW_SINCE: {"runAfter": {}, "type": "Compose", "inputs": "@" + since_param},
        WINDOW_BEFORE: {"runAfter": {}, "type": "Compose", "inputs": "@" + before_param},
        BATCH_DAYS: {
            "runAfter": {WINDOW_SINCE: ["Succeeded"], WINDOW_BEFORE: ["Succeeded"]},
            "type": "Compose",
            "inputs": batch_days,
        },
        EACH_BATCH: {
            "foreach": f"@createArray({', '.join(str(i) for i in range(BATCHES))})",
            "actions": inner,
            "runAfter": {BATCH_DAYS: ["Succeeded"]},
            "type": "Foreach",
            # All slices at once: this is what hides Outlook's per-email read time.
            "runtimeConfiguration": {"concurrency": {"repetitions": BATCHES}},
        },
    }
    return flow
