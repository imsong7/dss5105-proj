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
TOP = 100
DEFAULT_DAYS = 30


def _definition(endpoint: str, email: str, token: str) -> dict:
    # The app sends {"owner", "since", "before"} when it asks for a refresh.
    # "since" picks how far back to read; with no body it reads 30 days.
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
                                "includeAttachments": False,
                                "searchQuery": since,
                                "top": TOP,
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
                            "HTTP": {
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
                                    },
                                },
                                "runtimeConfiguration": {
                                    "contentTransfer": {"transferMode": "Chunked"}
                                },
                            }
                        },
                        "runAfter": {GET_EMAILS: ["Succeeded"]},
                        "type": "Foreach",
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
