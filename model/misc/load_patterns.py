"""
This module loads a JSON file of bug patterns into the SQLite database.
"""
import json
import sqlite3
import os
import argparse
import sys

# Ensure config can be imported when running directly
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(current_dir))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import config as DebugController

def load_patterns(json_file="BugPatterns.json"):
    """
    Loads patterns from a given JSON file into the SQLite database.
    """
    config = DebugController.APP_SETTINGS
    db_path = config.get('SQLITE_DB_PATH', 'patterns.db')
    
    # Resolve relative paths
    if not os.path.isabs(json_file):
        json_file = os.path.join(root_dir, json_file)
        
    if not os.path.isabs(db_path):
        db_path = os.path.join(root_dir, db_path)

    if not os.path.exists(json_file):
        print(f"Error: JSON file '{json_file}' not found.")
        return

    print(f"Loading patterns from {json_file}...")
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            patterns = json.load(f)
    except Exception as e:
        print(f"Failed to load JSON file: {e}")
        return

    print(f"Found {len(patterns)} patterns. Inserting into {db_path}...")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS BugPatterns (data TEXT)")
    
    count = 0
    for pattern in patterns:
        if '_id' in pattern:
            del pattern['_id']
            
        cursor.execute("INSERT INTO BugPatterns (data) VALUES (?)", (json.dumps(pattern),))
        count += 1
        
    conn.commit()
    conn.close()
    
    print(f"Successfully loaded {count} patterns into {db_path}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load bug patterns from JSON to SQLite")
    parser.add_argument(
        "--file", type=str, default="BugPatterns.json",
        help="Path to the JSON file containing the bug patterns"
    )
    args = parser.parse_args()
    
    load_patterns(args.file)
