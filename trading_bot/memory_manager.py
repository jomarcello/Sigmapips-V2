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

# Singleton instance voor het hele project
memory_manager = ProjectMemoryManager()

def save_project_progress(summary):
    """Sla projectvoortgang op in het geheugenbestand"""
    memory_manager.add_progress_update(summary)

def get_project_context():
    """Haal de volledige projectcontext op"""
    return memory_manager.get_latest_context()
