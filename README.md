# About
Email Exporter is a Prometheus server that connects to a Gmail account using OAuth2 credentials and scrapes its inbox based on a JSON mappings file. The server uses Prometheus' [client_python](https://github.com/prometheus/client_python) library for Python under the hood, with some minor tweaks.

# Generating credentials

1. Create an OAuth 2.0 credential of type "Desktop" to represent the application.
2. Download the JSON credentials and take note of the file's path
3. Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) if you don't have it, and then run the following command:
```bash
gcloud auth application-default login \
  --client-id-file path/to/credentials.json \
  --no-browser \
  --scopes "https://www.googleapis.com/auth/gmail.readonly"
```
4. You will need to execute the provided command in another terminal. An OAuth flow will begin in your browser, asking you to log in with the account you wish to authorize access for. If the browser doesn't open, you can click or copy the generated link instead.