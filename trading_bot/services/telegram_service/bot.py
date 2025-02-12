import os
import ssl
import asyncio
import logging
import aiohttp
from typing import Dict, Any

from telegram import Bot, Update
from telegram.ext import Application
from telegram.constants import ParseMode

# Gebruik relatieve import
from ..database.db import Database

# Rest van de code...
