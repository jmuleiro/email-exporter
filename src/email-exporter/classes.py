import re
import emoji
import logging as log
from html.parser import HTMLParser
from prometheus_client import Counter, Gauge, Summary, Histogram, Info, Enum

class EmailTemplate:
  """
  Email template class, which contain metric mappings
  """
  def __init__(self, template: dict) -> None:
    self.sender: str = template.get("sender")
    self.initialFilter = template.get("regexFilter", None)
    self.mappings = []
    for mp in template.get("mappings"):
      self.mappings.append(MetricMapping(mp))

class MetricMapping:
  """
  Metric/email mapping class
  """
  def __init__(self, mapping: dict) -> None:
    self.pattern = mapping.get("pattern")
    self.name = mapping.get("name", "Default Metric Name")
    self.description = mapping.get("description", "Default Metric Description")
    self.labels: list = mapping.get("labels", [])
    self.metricName = mapping.get("metric").get("name")
    #todo: add schema properties for metric attributes 
    #todo: i.e. namespace, unit, etc.
    match mapping.get("metric").get("type", "gauge"):
      case "counter":
        self.metric = CounterTs(mapping.get("metric").get("name"), 
                              self.description, 
                              labelnames=self.labels + ["timestamp"])
      case "summary":
        self.metric = SummaryTs(mapping.get("metric").get("name"),
                              self.description,
                              labelnames=self.labels + ["timestamp"])
      case "histogram":
        self.metric = HistogramTs(mapping.get("metric").get("name"),
                              self.description,
                              labelnames=self.labels + ["timestamp"])
      case "info":
        self.metric = InfoTs(mapping.get("metric").get("name"),
                              self.description)
      case "enum":
        self.metric = EnumTs(mapping.get("metric").get("name"),
                              self.description,
                              labelnames=self.labels + ["timestamp"],
                              states=mapping.get("metric").get("states"))
      case "gauge":
        self.metric = GaugeTs(mapping.get("metric").get("name"), 
                            self.description,
                            labelnames=self.labels + ["timestamp"])

class MailParser(HTMLParser):
  def __init__(self, *, convert_charrefs: bool = True) -> None:
    super().__init__(convert_charrefs=convert_charrefs)
    
    #? Internal metrics
    self.errorsCount = Counter('mail_exporter_errors', 
                               "Number of mail exporter errors",
                               ("name", "description", "metric"))
    self.mismatchesCount = Counter('mail_exporter_mismatches',
                                  "Number of mail exporter regex mismatches in messages",
                                  ("template"))
  
  #? Timestamp property
  @property
  def timestamp(self):
    return self._timestamp
  @timestamp.setter
  def timestamp(self, value):
    # todo: validation
    self._timestamp = value

  #? Template property
  @property
  def template(self) -> EmailTemplate:
    return self._template
  @template.setter
  def template(self, value: EmailTemplate):
    self._template = value

  def handle_data(self, data: str):
    """
    Parses Gmail message payloads and drops unnecessary HTML tags and attributes.
    """
    #? Drop all lines that match the initial filter
    if self.template.initialFilter and not re.findall(self.template.initialFilter, data):
      return
    #? Remove emoji
    data = emoji.replace_emoji(data, '')
    data = re.sub(r'\D{0,9}(?>\{.*\})|(?>\@\D.*)', '', data)
    #? Remove whitespaces and commas
    data = re.sub(r'\n|\r|\t|\0|,', '', data).strip()
    self.processData(data)
  
  def processData(self, _d: str):
    for mp in self.template.mappings:
      if result := re.search(mp.pattern, _d):
        self.processMapping(result.groupdict(), mp)
        return
    log.warning(f"No mapping for '{_d}'")
    self.mismatchesCount.labels({"template": self.template.sender}).inc()
  
  def processMapping(self, result: dict[str, str], mapping: MetricMapping):
    log.debug(f"Processing metric '{mapping.metricName}' type '{type(mapping.metric)}' with values: {result}, result type: {type(result)}")
    if (len(mapping.labels) and len(mapping.labels) != (len(result) - 1)):
      log.error(f"Labels and capturing groups mismatch: Got {len(mapping.labels)} labels but {len(result)} groups (including value)")
      self.errorsCount.labels(name=mapping.metricName, description=mapping.description, metric=mapping.metric._name).inc()
      return

    match mapping.metric:
      case CounterTs() | GaugeTs():
        value = float(result.pop("value"))
        mapping.metric.incTimestamped(result, value, self.timestamp)
      case HistogramTs() | SummaryTs():
        value = float(result.pop("value"))
        mapping.metric.observeTimestamped(result, value, self.timestamp)
      case InfoTs():
        mapping.metric.infoTimestamped(result, self.timestamp)
      case EnumTs():
        state = result.pop("state")
        mapping.metric.stateTimestamped(result, state, self.timestamp)

class GaugeTs(Gauge):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  #fyi https://github.com/prometheus/client_python/issues/588
  def collect(self):
    metrics = super().collect()
    for metric in metrics:
      samples = []
      for sample in metric.samples:
        timestamp = sample.labels.pop("timestamp", None)
        samples.append(type(sample)(sample.name, sample.labels, sample.value, timestamp, sample.exemplar))
      metric.samples = samples
    return metrics

  def incTimestamped(self, labels: dict[str, str], value: float, timestamp):
    """
    Increments timestamped gauge with labels
    """
    labels.update({
      "timestamp": timestamp
    })
    self.labels(**labels).inc(value)

class CounterTs(Counter):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, *kwargs)

  def collect(self):
    metrics = super().collect()
    for metric in metrics:
      samples = []
      for sample in metric.samples:
        timestamp = sample.labels.pop("timestamp", None)
        samples.append(type(sample)(sample.name, sample.labels, sample.value, timestamp, sample.exemplar))
      metric.samples = samples
    return metrics
  
  def incTimestamped(self, labels: dict[str, str], value: float, timestamp):
    """
    Increments timestamped counter with labels
    """
    labels.update({
      "timestamp": timestamp
    })
    self.labels(**labels).inc(value)

class HistogramTs(Histogram):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, *kwargs)
  
  def collect(self):
    metrics = super().collect()
    for metric in metrics:
      samples = []
      for sample in metric.samples:
        timestamp = sample.labels.pop("timestamp", None)
        samples.append(type(sample)(sample.name, sample.labels, sample.value, timestamp, sample.exemplar))
      metric.samples = samples
    return metrics
  
  def observeTimestamped(self, labels: dict[str, str], value: float, timestamp):
    """
    Observes timestamped value
    """
    labels.update({
      "timestamp": timestamp
    })
    self.labels(**labels).observe(value)

class SummaryTs(Summary):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, *kwargs)
  
  def collect(self):
    metrics = super().collect()
    for metric in metrics:
      samples = []
      for sample in metric.samples:
        timestamp = sample.labels.pop("timestamp", None)
        samples.append(type(sample)(sample.name, sample.labels, sample.value, timestamp, sample.exemplar))
      metric.samples = samples
    return metrics
  
  def observeTimestamped(self, labels: dict[str, str], value: float, timestamp):
    """
    Observes timestamped value
    """
    labels.update({
      "timestamp": timestamp
    })
    self.labels(**labels).observe(value)

class InfoTs(Info):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, *kwargs)
  
  def collect(self):
    metrics = super().collect()
    for metric in metrics:
      samples = []
      for sample in metric.samples:
        timestamp = sample.labels.pop("timestamp", None)
        samples.append(type(sample)(sample.name, sample.labels, sample.value, timestamp, sample.exemplar))
      metric.samples = samples
    return metrics
  
  def infoTimestamped(self, labels: dict[str, str], timestamp):
    labels.update({
      "timestamp":  timestamp
    })
    self.info(labels)

class EnumTs(Enum):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, *kwargs)
  
  def collect(self):
    metrics = super().collect()
    for metric in metrics:
      samples = []
      for sample in metric.samples:
        timestamp = sample.labels.pop("timestamp", None)
        samples.append(type(sample)(sample.name, sample.labels, sample.value, timestamp, sample.exemplar))
      metric.samples = samples
    return metrics
  
  def stateTimestamped(self, labels: dict[str, str], state: str, timestamp):
    labels.update({
      "timestamp": timestamp
    })
    self.labels(**labels).state(state)