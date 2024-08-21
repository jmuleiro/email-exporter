import logging

class LogFormatter(logging.Formatter):
  grey = "\x1b[38;5;254m"
  yellow = "\x1b[38;5;178m"
  cyan = "\x1b[38;5;39m"
  red = "\x1b[38;5;196m"
  bold_red = "\x1b[38;5;160m"
  reset = "\x1b[0m"
  _fmt = "%(asctime)s::%(name)s::%(levelname)s>> %(message)s (%(filename)s:%(lineno)d)"

  FORMATS = {
    logging.DEBUG: grey + _fmt + reset,
    logging.INFO: grey + f"%(asctime)s::%(name)s::{cyan}%(levelname)s{reset}{grey}>> %(message)s (%(filename)s:%(lineno)d)" + reset,
    logging.WARNING: yellow + _fmt + reset,
    logging.ERROR: red + _fmt + reset,
    logging.CRITICAL: bold_red + _fmt + reset
  }

  def format(self, record):
    return logging.Formatter(self.FORMATS.get(record.levelno)).format(record)

def getLogger(logLevel) -> logging.Logger:
  logger = logging.getLogger()
  logger.setLevel(logLevel)
  ch = logging.StreamHandler()
  ch.setLevel(logLevel)
  ch.setFormatter(LogFormatter())
  logger.addHandler(ch)
  return logger