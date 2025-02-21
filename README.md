# GCP Billing Cost Reporter with Slack Notifications

This repository retrieves GCP billing data from BigQuery, aggregates costs by SKU and project, calculates cost deltas, and sends a formatted report to Slack. A GitHub Actions workflow builds a Docker image and pushes it to GitHub Artifact Registry. You can then deploy the image to GCP Cloud Run using the Cloud Console UI.

---

## Prerequisites

- **Google Cloud Project** with billing enabled.
- **Google Service Account** with the following roles:
  - *BigQuery Data Viewer* (`roles/bigquery.dataViewer`)
  - *BigQuery Job User* (`roles/bigquery.jobUser`)
- **Slack Workspace** and a Slack Bot with these scopes:
  - `chat:write`
  - `conversations:read`
  - `conversations:write`
- Docker (if you plan to build images locally)
- A GitHub repository to host this code

---

## Setup

### 1. Create a Google Service Account

1. In the [Google Cloud Console](https://console.cloud.google.com/), navigate to **IAM & Admin > Service Accounts**.
2. Create a new service account (e.g., `billing-reporter-sa`).
3. Grant the service account the roles:
   - *BigQuery Data Viewer*
   - *BigQuery Job User*
4. Create and download a JSON key file.
5. Save the key file at the path specified in the code (default: `/var/secrets/billing-sa`), or update the `SERVICE_ACCOUNT_FILE` variable accordingly.

### 2. Create a Slack Bot with Necessary Privileges


#### - Create a Slack App

1. Go to [Slack API: Your Apps](https://api.slack.com/apps).
2. Click **"Create New App"**.
3. Choose **"From scratch"**.
4. Enter an **App Name** (e.g., `GCP Billing Reporter Bot`).
5. Select the **Development Slack Workspace** where you want to install the app.
6. Click **"Create App"**.

#### - Configure OAuth & Permissions

1. In your app's settings, click **"OAuth & Permissions"**.
2. Under **"Bot Token Scopes"**, add the following scopes:
   - **`chat:write`** — Allows the bot to send messages.
   - **`conversations:read`** — Allows the bot to read channel and conversation information.
   - **`conversations:write`** — Allows the bot to manage conversations.
   - *(Optional)* **`im:history`** — Allows the bot to read direct message history, if needed.
3. Click **"Save Changes"**.

#### - Install the App to Your Workspace

1. In the **"OAuth & Permissions"** page, click **"Install App to Workspace"**.
2. Review the permissions, then click **"Allow"**.
3. After installation, copy the **Bot User OAuth Token** (it starts with `xoxb-`).  
   This token is needed to authenticate API requests.

#### - Use the Bot Token in Your Application

- Store your **Bot User OAuth Token** securely (for example, in environment variables or a secrets manager).
- Use this token in your application when calling Slack API methods such as `chat.postMessage`.

### 2. Set Environment Variables

Configure the following environment variables (for example, in a `.env` file or via your deployment settings):

```env
SLACK_API_TOKEN=your-slack-bot-token
SLACK_CHANNEL_ID=your-channel-or-user-id
SEND_PROJECT_BREAKDOWN=true
SEND_THREAD_DETAILS=true

