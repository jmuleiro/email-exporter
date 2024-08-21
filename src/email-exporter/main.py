import re
import os
import json
import time
import base64
from logger import getLogger
from jsonschema import validate
from traceback import print_exc
from classes import EmailTemplate, MailParser
from prometheus_client import start_http_server
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

class MailExporter():
  def __init__(self, logLevel: str = 'INFO'):
    #? Setup logging
    self.log = getLogger(logLevel)
    self.mappings: list[EmailTemplate] = []
    self.parser = MailParser()
  
  #? Mappings property
  @property
  def mappings(self) -> list[EmailTemplate]:
    return self._mappings
  @mappings.setter
  def mappings(self, value: list[EmailTemplate]):
    self._mappings = value
  
  #? Parser property
  @property
  def parser(self) -> MailParser:
    return self._parser
  @parser.setter
  def parser(self, value: MailParser):
    self._parser = value
  
  #? Mail API Service property
  @property
  def mailApi(self) -> object:
    return self._mailApi
  @mailApi.setter
  def mailApi(self, value: object):
    self._mailApi = value

  #? User ID property
  @property
  def userId(self) -> str:
    return self._userId
  @userId.setter
  def userId(self, value: str):
    self._userId = value
    
  #? Max Results property
  @property
  def maxResults(self) -> str:
    return self._maxResults
  @maxResults.setter
  def maxResults(self, value: str):
    #todo: validation
    self._maxResults = value

  def bootstrap(self):
    #? Get JSON mappings
    self.log.debug("Getting mappings")
    mappingsFile = os.getenv("MAPPINGS_FILE", "scripts/gmail-lookup/mappings.json")
    with open(mappingsFile, 'r') as stream:
      mappingsDict: dict = json.loads(stream.read())
    self.log.debug(f"Got mappings from {mappingsFile}")

    #? Mappings validation
    self.log.debug("Getting schema")
    schemaFile = os.getenv("SCHEMA_FILE", "scripts/gmail-lookup/schema.json")
    with open(schemaFile, 'r') as stream:
      schema = json.loads(stream.read())
    self.log.debug(f"Got schema from {schemaFile}. Validating mappings")
    validate(instance=mappingsDict, schema=schema)
    self.log.info("Mappings are valid")

    self.log.debug("Parsing mappings")
    for template in mappingsDict.get("templates"):
      self.mappings.append(EmailTemplate(template))
    self.log.debug("Mappings parse successful")

  def backwardsLookup(self, query: str):
    dateRegex = r"^\d{2}\/\d{2}\/\d{4}$"
    from datetime import datetime, timedelta
    if (gmailDateFrom := os.getenv("MAIL_DATE_FROM", False)):
      if not (re.match(dateRegex, gmailDateFrom)
              or datetime.strptime(gmailDateFrom, "%m/%d/%Y")): 
        raise ValueError("Date from should be MM/DD/YYYY")
    else:
      gmailDateFrom = (datetime.now() - timedelta(os.getenv("MAIL_FROM_DAYS", 30))).strftime("%m/%d/%Y")
    query += f"after:{gmailDateFrom} "

    #? If MAIL_DATE_TO is not set lookup everything after gmailDateFrom
    if (gmailDateTo := os.getenv("MAIL_DATE_TO", False)):
      if not (re.match(dateRegex, gmailDateFrom)
              or datetime.strptime(gmailDateTo, "%m/%d/%Y")):
        raise ValueError("Date to should be MM/DD/YYYY")
      query += f"before:{gmailDateTo} "
    self.processMappings(query, True)
    self.log.info("Backwards lookup done")

  def processMappings(self, query: str, backwardsLookup: bool = False):
    #todo: multiple senders (templates) support
    self.log.debug(f"Iterating over {len(self.mappings)} templates")
    for index, template in enumerate(self.mappings):
      self.log.debug(f"Template n°{index+1}")
      finalQuery = query + f"from:{template.sender} "
      self.log.debug(f"Gmail Query: '{finalQuery}', userId: '{self.userId}'")
      self.parser.template = template
      self.log.debug("Iterating over results")
      for message in self.getEmails(finalQuery):
        self.parser.timestamp = message["internalDate"]
        #todo use period in seconds global instead of hardcoded value
        if not (backwardsLookup or self.parser.timestamp / 1000 < time.time() - 30):
          self.log.debug(f"Skipping message because it was older than {30} seconds")
          continue
        self.parser.feed(base64.urlsafe_b64decode(message["payload"]["body"]["data"]).decode())

  def getEmails(self, query: str):
    self.log.debug(f"Getting emails, query: '{query}'")
    nextPageToken = None
    resultsCount = 0
    #? Do/While, we want to get mails list first and then see if a nextPageToken exists
    while True:
      self.log.debug(f"Results iteration no.: '{resultsCount :+= 1}'")
      response = (self.mailApi
                  .users()
                  .threads()
                  .list(userId=self.userId, maxResults=self.maxResults, q=query, pageToken=nextPageToken)
                  .execute())
      mailThreads = response.get("threads", [])
      nextPageToken = response.get("nextPageToken", None)

      if not mailThreads:
        self.log.debug("Got no threads")
        return

      for mThread in mailThreads:
        self.log.debug(f"Getting mail thread '{mThread["id"]}'")
        #todo: are multiple messages possible?
        yield ((self.mailApi.users().threads().get(userId=self.userId, id=mThread["id"])).execute())["messages"][0]

      if nextPageToken:
        #todo: make configurable (from parameter, this function should not interact with env)
        sleptSeconds = 1
        self.log.debug(f"Got nextPageToken, sleeping for {sleptSeconds} second(s)...")
        time.sleep(sleptSeconds)
      else:
        self.log.debug("Got to the end of the mail list")
        return

  def main(self):
    self.log.debug("Getting credentials")
    creds = None
    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
    tokenFile = os.getenv("OAUTH_TOKEN_FILENAME", "token.json")
    credentialsFile = os.getenv("OAUTH_CREDENTIALS_FILENAME", "scripts/gmail-lookup/credentials2.json")

    if os.path.exists(tokenFile):
      creds = Credentials.from_authorized_user_file(tokenFile, SCOPES)
      self.log.debug(f"Found token file: '{tokenFile}'")
    else:
      self.log.debug(f"No token file at: '{tokenFile}'")

    #? If credentials are invalid, log in
    if not creds or not creds.valid:
      self.log.debug("Credentials are invalid, attempting refresh")
      if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        self.log.debug("Refreshed credentials")
      else:
        self.log.debug(f"Refresh not possible, starting OAuth flow with credentials at '{credentialsFile}'")
        flow = InstalledAppFlow.from_client_secrets_file(credentialsFile, SCOPES)
        creds = flow.run_local_server()
        self.log.debug("OAuth flow completed successfully")

      with open(tokenFile, "w") as token:
        token.write(creds.to_json())
        self.log.debug(f"Wrote token file to '{tokenFile}'")
    else:
      self.log.debug("Credentials are valid")

    exitCode = 0
    gmailQuery = ""
    self.maxResults = os.getenv("GMAIL_RESULTS_PER_PAGE", "100")
    self.userId = os.getenv("GMAIL_USER_ID", "me")

    try:
      #? Prometheus Server
      server, t = start_http_server(int(os.getenv("PORT", "8000")))

      #? Build Gmail API
      self.log.info("Building Gmail API")
      self.mailApi = build("gmail", "v1", credentials=creds)
      if os.getenv("BACKWARDS_LOOKUP", True):
        self.log.info("Backwards lookup is enabled")
        self.backwardsLookup(gmailQuery)
      else:
        self.log.info("Backwards lookup is disabled")

      period = float(os.getenv("MAIL_EXPORTER_PERIOD_SECONDS", 30))
      newerThanHours = os.getenv("MAIL_EXPORTER_NEWER_THAN_HOURS", 1)
      self.log.info(f"Watching {len(self.mappings)} template(s) every {period} seconds")
      while True:
        self.log.debug(f"Looking for messages in the last {newerThanHours} hour(s)")
        query = gmailQuery + f"newer_than:{newerThanHours}h "
        self.processMappings(query)
        self.log.debug(f"Sleeping {period}s...")
        time.sleep(period)

    except HttpError as e:
      self.log.critical(f"HttpError: {e}")
      print_exc()
      exitCode = 1
    except Exception as e:
      self.log.critical(f"{e.__class__.__name__}: {e}")
      print_exc()
      exitCode = 1
    finally:
      server.shutdown()
      t.join()
      exit(exitCode)

if __name__ == "__main__":
  exporter = MailExporter(os.getenv("LOG_LEVEL"))
  exporter.bootstrap()
  exporter.main()