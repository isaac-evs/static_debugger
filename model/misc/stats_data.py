"""
This module gets the stats from the database.
"""
from typing import Any, Dict, List, Tuple
import sqlite3
import json
import config as DebugController

ASTRanking = Tuple[List[str], List[int]]

def get_stats() -> Dict[str, Any]:
    """ This function obtains the stats from the DB collection.
    
    :rtype: Dict[str, Any]
    """
    config = DebugController.APP_SETTINGS
    db_path = config.get('SQLITE_DB_PATH', 'patterns.db')
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT data FROM BugPatterns")
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []
        
    data_items = [json.loads(row[0]) for row in rows]
    
    total_bugfixes = len(data_items)
    
    unique_bugfixes_set = set()
    unique_fixes_set = set()
    unique_bugs_set = set()
    
    fixes_ast_counts = {}
    bugs_ast_counts = {}
    
    for data in data_items:
        fix_md = data.get('fix_metadata', {})
        bug_md = data.get('bug_metadata', {})
        
        fix_hex = fix_md.get('hexdigest')
        bug_hex = bug_md.get('hexdigest')
        
        if fix_hex and bug_hex:
            unique_bugfixes_set.add((fix_hex, bug_hex))
        if fix_hex:
            unique_fixes_set.add(fix_hex)
        if bug_hex:
            unique_bugs_set.add(bug_hex)
            
        fix_ast = fix_md.get('ast_type')
        if fix_ast:
            fixes_ast_counts[fix_ast] = fixes_ast_counts.get(fix_ast, 0) + 1
            
        bug_ast = bug_md.get('ast_type')
        if bug_ast:
            bugs_ast_counts[bug_ast] = bugs_ast_counts.get(bug_ast, 0) + 1
            
    # Sort and rank
    fixes_ast_sorted = sorted(fixes_ast_counts.items(), key=lambda x: x[1], reverse=True)
    bugs_ast_sorted = sorted(bugs_ast_counts.items(), key=lambda x: x[1], reverse=True)
    
    ranking_fixes = (
        [item[0] for item in fixes_ast_sorted],
        [item[1] for item in fixes_ast_sorted]
    )
    ranking_bugs = (
        [item[0] for item in bugs_ast_sorted],
        [item[1] for item in bugs_ast_sorted]
    )
    
    stats_data = {
        'total_bugfixes': total_bugfixes,
        'unique_bugfixes': len(unique_bugfixes_set),
        'unique_fixes': len(unique_fixes_set),
        'ranking_fixes': ranking_fixes,
        'unique_bugs': len(unique_bugs_set),
        'ranking_bugs': ranking_bugs
    }
    return stats_data

if __name__ == "__main__":
    get_stats()