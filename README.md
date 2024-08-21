# Email Exporter for Prometheus
## About
Email Exporter is a Prometheus server that connects to a Gmail account using OAuth2 credentials and scrapes its inbox based on a JSON mappings file. The server uses Prometheus' [client_python](https://github.com/prometheus/client_python) library for Python under the hood, with some minor tweaks.

# Setup
## Generating credentials
1. Create an [OAuth 2.0 credential](https://developers.google.com/identity/protocols/oauth2/native-app) of type "Desktop" to represent the application.
_Note: You don't need to publish the OAuth app for review, you can instead configure the app as External and add the desired account as a testing user._
2. Download the JSON credentials and take note of the file's path.
3. Install the [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) if you don't have it, and then run the following command:
```bash
gcloud auth application-default login \
  --client-id-file path/to/credentials.json \
  --no-browser \
  --scopes "https://www.googleapis.com/auth/gmail.readonly"
```
The command above will output another command to execute in another terminal, and will idle waiting for an input.
4. When you execute the second command in another terminal, an OAuth flow will begin in your browser, asking you to log in with the account you wish to authorize access for. If the browser doesn't open, you can click or copy the generated link instead.
5. Once you've logged in, the second terminal will output a localhost link at the end, which you need to copy and paste into the first terminal.
6. The SDK will output a message stating `Credentials saved to file`. This means that your environment should now have a `GOOGLE_APPLICATION_CREDENTIALS` variable containing the path to the generated OAuth2 refresh token. You need to pass that JSON file's path as the variable `OAUTH_TOKEN_FILENAME`.