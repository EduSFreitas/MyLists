from logging.handlers import RotatingFileHandler
from MyLists import app
import logging
import os
import sys


formatter = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
handler = RotatingFileHandler("MyLists/log/mylists.log", maxBytes=10000000, backupCount=5)
handler.setLevel(logging.INFO)
handler.setFormatter(formatter)
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

if not os.path.isfile('./config.ini'):
    print("Config file not found. Exit.")
    sys.exit()

if __name__ == "__main__":
    app.run(debug=False)
