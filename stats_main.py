# -* coding: utf-8 -*-

import csv  #
import codecs  # used for text encoding in config parser
import argparse  # good argument parser
import re  # for parsing ticket no from description
from openpyxl import load_workbook  #
from configparser import ConfigParser  # able to read configuration file

from config_loader import config_loader


def main():
    print("test")
    config = config_loader()