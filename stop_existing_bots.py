#!/usr/bin/env python3
"""
Script to check for and stop any existing bot instances.
Run this before starting a new bot to avoid Telegram API conflicts.
"""

import os
import sys
import logging
import signal
import time
import subprocess
import asyncio
from telegram import Bot
from telegram.error import TelegramError

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Lock file path - Using Railway's tmp directory which persists between restarts
LOCK_FILE = "/tmp/telegbot_instance.lock"
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7328581013:AAFMGu8mz746nbj1eh6BuOp0erKl4Nb_-QQ")

def find_bot_processes():
    """Find any running bot processes by looking for python with main.py in their command line"""
    try:
        # Use more aggressive search to find any python process that might be running the bot
        cmd = ["ps", "-ef"]
        result = subprocess.run(cmd, shell=False, capture_output=True, text=True)
        
        # Parse the output to get process IDs for any Python process
        processes = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            if 'python' in line and ('main.py' in line or 'start_clean.py' in line):
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    logger.info(f"Found potential bot process: PID {pid}, CMD: {line}")
                    try:
                        processes.append(int(pid))
                    except ValueError:
                        pass
        
        return processes
    except Exception as e:
        logger.error(f"Error finding bot processes: {e}")
        return []

def check_lock_file():
    """Check if the lock file exists and get the PID it contains"""
    if not os.path.exists(LOCK_FILE):
        logger.info("No lock file found. No bot instance is running or it didn't exit cleanly.")
        return None
    
    try:
        # Read the PID from the lock file
        with open(LOCK_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        # Check if the process is actually running
        try:
            os.kill(pid, 0)  # This throws an error if the process is not running
            logger.info(f"Bot instance is running with PID {pid}")
            return pid
        except OSError:
            logger.info(f"Stale lock file found. PID {pid} is not running.")
            remove_lock_file()
            return None
    except Exception as e:
        logger.error(f"Error checking lock file: {e}")
        return None

def remove_lock_file():
    """Remove the lock file"""
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
            logger.info(f"Removed lock file at {LOCK_FILE}")
        except Exception as e:
            logger.error(f"Error removing lock file: {e}")

def create_lock_file(pid=None):
    """Create a lock file with the current PID"""
    try:
        pid = pid or os.getpid()
        with open(LOCK_FILE, 'w') as f:
            f.write(str(pid))
        logger.info(f"Created lock file at {LOCK_FILE} with PID {pid}")
        return True
    except Exception as e:
        logger.error(f"Error creating lock file: {e}")
        return False

def stop_process(pid):
    """Stop a process with the given PID"""
    try:
        logger.info(f"Attempting to stop process with PID {pid}")
        try:
            os.kill(pid, signal.SIGTERM)
        except:
            pass
        
        # Give the process a moment to shut down
        time.sleep(2)
        
        # Check if it's still running
        try:
            os.kill(pid, 0)
            logger.warning(f"Process {pid} did not stop with SIGTERM. Trying SIGKILL...")
            try:
                os.kill(pid, signal.SIGKILL)
                time.sleep(1)
            except:
                pass
            
            # Check if it's still running after SIGKILL
            try:
                os.kill(pid, 0)
                logger.error(f"Process {pid} still running after SIGKILL!")
                return False
            except OSError:
                logger.info(f"Process {pid} killed with SIGKILL successfully")
                return True
        except OSError:
            logger.info(f"Process {pid} stopped successfully with SIGTERM")
            return True
            
    except Exception as e:
        logger.error(f"Error stopping process {pid}: {e}")
        return False

async def clear_telegram_api():
    """Try to clear any active Telegram API sessions"""
    try:
        logger.info("Attempting to clear Telegram API sessions...")
        bot = Bot(token=BOT_TOKEN)
        
        # Get webhook info
        try:
            webhook_info = await bot.get_webhook_info()
            if webhook_info.url:
                logger.info(f"Found active webhook: {webhook_info.url}")
                logger.info("Removing webhook...")
                await bot.delete_webhook(drop_pending_updates=True)
                logger.info("Webhook removed successfully")
        except Exception as e:
            logger.error(f"Error checking webhook: {e}")
        
        # Try to make a test getUpdates call to clear any remaining sessions
        try:
            logger.info("Sending dummy getUpdates request to clear sessions...")
            await bot.get_updates(timeout=1, offset=-1, limit=1)
            logger.info("Dummy getUpdates request completed")
        except Exception as e:
            logger.info(f"Expected exception from getUpdates: {e}")
            # This exception is expected as we're trying to clear an existing session
        
        return True
    except Exception as e:
        logger.error(f"Error clearing Telegram API sessions: {e}")
        return False

async def main():
    """Main function to stop any existing bot instances"""
    logger.info("Checking for existing bot instances...")
    
    # Check the lock file first
    pid_from_lock = check_lock_file()
    if pid_from_lock:
        stop_process(pid_from_lock)
    
    # Also look for any bot processes in case lock file doesn't exist or has wrong PID
    running_processes = find_bot_processes()
    if running_processes:
        logger.info(f"Found {len(running_processes)} bot processes running: {running_processes}")
        for pid in running_processes:
            # Don't try to kill our own process
            current_pid = os.getpid()
            if pid != current_pid:
                stop_process(pid)
    else:
        logger.info("No bot processes found running")
    
    # Always remove lock file to ensure clean start
    remove_lock_file()
    
    # Clear any active Telegram API sessions
    await clear_telegram_api()
    
    # Create a new lock file for this process
    create_lock_file()
    
    logger.info("Done. It's now safe to start a new bot instance.")

if __name__ == "__main__":
    asyncio.run(main()) 
