import os
from datetime import datetime

class ProjectMemoryManager:
    def __init__(self, memory_file="project_memory.md"):
        self.memory_file = memory_file
        self.ensure_memory_file_exists()
    
    def ensure_memory_file_exists(self):
        if not os.path.exists(self.memory_file):
            with open(self.memory_file, 'w', encoding='utf-8') as f:
                f.write("# SigmapipsAI Trading Bot - Project Memory\n\n")
                f.write("## Belangrijke Beslissingen & Voortgang\n\n")
    
    def add_progress_update(self, summary):
        """Voegt een voortgangsupdate toe aan het geheugenbestand"""
        with open(self.memory_file, 'a', encoding='utf-8') as f:
            f.write(f"\n### Update - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"{summary}\n")
            f.write("\n---\n")
    
    def get_latest_context(self):
        """Leest het gehele geheugenbestand"""
        with open(self.memory_file, 'r', encoding='utf-8') as f:
            return f.read() 
