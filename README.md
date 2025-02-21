# GCP Billing Cost Reporter with Slack Notifications

This repository retrieves daily GCP billing data from BigQuery (reporting on the day before yesterday due to export delays), aggregates costs by SKU and project, calculates cost deltas, and sends a formatted report to Slack. A GitHub Actions workflow builds a Docker image and pushes it to GitHub Artifact Registry. You can then deploy the image to GCP Cloud Run using the Cloud Console UI.

![GCP Billing Bot](https://raw.githubusercontent.com/himaster/gcp-billing-bot/refs/heads/main/pic.png)
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
```

## Running the Code Locally
This project includes a `Dockerfile` that defines the image for the GCP Billing Cost Reporter. You can run the application locally using Docker Compose.
`docker-compose up --build`

## Deploying to GCP Cloud Run via UI with Secret Manager Integration

This application requires sensitive data—such as secret environment variables and a service account JSON file—to operate. To keep these secrets secure, store them in Secret Manager and mount them to your Cloud Run service.

### 1. Create Secrets in Secret Manager

1. **Open Secret Manager:**
   - Go to the [Secret Manager Console](https://console.cloud.google.com/security/secret-manager).

2. **Create Secrets:**
   - **SLACK_API_TOKEN:**
     - Click **"Create Secret"**.
     - Name it `SLACK_API_TOKEN` and paste your Slack Bot token.
   - **SLACK_CHANNEL_ID:**
     - Create another secret named `SLACK_CHANNEL_ID` and paste your target channel or user ID.
   - **Service Account File:**
     - Create a secret (e.g., `billing-sa`) and upload your service account JSON file contents.

### 2. Deploy Your Service in Cloud Run

1. **Open Cloud Run:**
   - Go to the [Cloud Run Console](https://console.cloud.google.com/run).

2. **Create a New Service:**
   - Click **"Create Service"**.
   - Enter a service name (e.g., `gcp-billing-reporter`).

3. **Specify the Container Image:**
   - In **Container image URL**, enter the URL of your Docker image (for example:  
     `ghcr.io/<your-github-username>/<repository-name>:latest`).

4. **Configure Environment Variables and Secrets:**

   - In the **Variables & Secrets** section, add the following environment variables by clicking **"Reference a Secret"** for each:
     - **SLACK_API_TOKEN:**  
       Select the secret version of your `SLACK_API_TOKEN`.
     - **SLACK_CHANNEL_ID:**  
       Select the secret version of your `SLACK_CHANNEL_ID`.

   Your application also uses two non-secret environment variables. In the same **Variables & Secrets** section, add these as plain environment variables:

   - **SEND_PROJECT_BREAKDOWN**:  
     - Click **"Add Variable"**.
     - Enter `SEND_PROJECT_BREAKDOWN` as the name and set its value (for example, `true`).

   - **SEND_THREAD_DETAILS**:  
     - Click **"Add Variable"**.
     - Enter `SEND_THREAD_DETAILS` as the name and set its value (for example, `true`).

   - **Mount the Service Account File:**
     - Still in the **Variables & Secrets** section, click **"Add Mount"**.
     - Choose **Secret** and select your `billing-sa-json` secret.
     - Set the mount path to:  
       `/var/secrets/billing-sa`
     - This makes the service account file available to your application.

5. **Set Additional Configuration:**
   - Choose your region (e.g., `europe-west4`).
   - Configure CPU, memory, and concurrency as needed.
   - Optionally, add any other environment variables your application requires.

## Cleanup
Remove any unused resources (such as Cloud Run services or service accounts) to avoid unnecessary charges.
6. **Deploy:**
   - Click **"Create"** to deploy your Cloud Run service.
