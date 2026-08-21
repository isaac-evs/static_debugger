import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

import logger as AbinLogging

# Initialize configurations before loading Model
import config as DebugController


def load_settings():
   config_path = Path(__file__).parent.joinpath("controller", "config.yml")
   if config_path.exists():
       with open(config_path, "r") as f:
           config_data = yaml.full_load(f)
           DebugController.APP_SETTINGS = config_data
   else:
       # Fallback defaults
       DebugController.APP_SETTINGS = {
           "SQLITE_DB_PATH": "patterns.db",
           "SUSPICIOUSNESS_THRESHOLD": "0",
       }

   # Establish connection status blindly for CLI (assumes user has DB running)
   DebugController.DB_STATUS = DebugController.ConnectionStatus.Established

   # Configure timeout
   DebugController.TEST_TIMEOUT = float(
       DebugController.APP_SETTINGS.get("MAXIMUM_TEST_TIMEOUT", "1.0")
   )


load_settings()

from AbinModel import AbinModel, parse_csv_data
from model.HypothesisRefinement import AbductionSchema


def main():
   parser = argparse.ArgumentParser(description="AbinDebugger CLI - Headless Mode")
   parser.add_argument(
       "--mine", type=str, help="Mine bug patterns from a GitHub repo (format: owner/repo) and insert into DB"
   )
   parser.add_argument(
       "--model", type=str, help="Path to defective .py file"
   )
   parser.add_argument(
       "--tests", type=str, help="Path to test suite .csv file"
   )
   parser.add_argument(
       "--func", type=str, help="Name of the target function to debug"
   )
   parser.add_argument(
       "--complexity", type=int, default=3, help="Max hypothesis complexity"
   )
   parser.add_argument(
       "--schema",
       type=str,
       default="DFS",
       choices=["DFS", "BFS", "A_STAR"],
       help="Search strategy",
   )

   args = parser.parse_args()

   # Set up basic console logging
   import logging

   logging.basicConfig(level=logging.DEBUG, format="%(message)s")
   AbinLogging.debugging_logger.setLevel(logging.DEBUG)

   # Handle mining mode
   if args.mine:
       parts = args.mine.split('/')
       if len(parts) != 2:
           print("Error: --mine argument must be in format 'owner/repo' (e.g. psf/requests)")
           sys.exit(1)

       owner, repo = parts
       print(f"Mining bug commits from {owner}/{repo}... this may take a moment.")

       import model.misc.bug_mining as bug_mining
       import json
       import sqlite3

       repo_data, bugfixes_data = bug_mining.mineBugCommitsFromRepo(owner, repo)

       if bugfixes_data:
           print("Connecting to SQLite to insert patterns...")
           db_path = DebugController.APP_SETTINGS.get('SQLITE_DB_PATH', 'patterns.db')
           conn = sqlite3.connect(db_path)
           cursor = conn.cursor()
           cursor.execute("CREATE TABLE IF NOT EXISTS RepoData (data TEXT)")
           cursor.execute("CREATE TABLE IF NOT EXISTS BugPatterns (data TEXT)")
           cursor.execute("INSERT INTO RepoData (data) VALUES (?)", (json.dumps(repo_data),))
           for item in bugfixes_data:
               cursor.execute("INSERT INTO BugPatterns (data) VALUES (?)", (json.dumps(item),))
           conn.commit()
           conn.close()
           print(f"Successfully inserted {len(bugfixes_data)} bug patterns into SQLite!")
       else:
           print("No bugs found to insert.")
       return

   # If not mining, we need the standard arguments
   if not args.model or not args.tests or not args.func:
       print("Error: --model, --tests, and --func are required for debugging. Or use --mine to populate DB.")
       parser.print_help()
       sys.exit(1)

   # Load and parse tests
   print(f"Loading test suite from {args.tests}...")
   df = pd.read_csv(args.tests, keep_default_na=False)
   test_cases, _ = parse_csv_data(df)

   # Map schema enum
   schema_map = {
       "DFS": AbductionSchema.DFS,
       "BFS": AbductionSchema.BFS,
       "A_STAR": AbductionSchema.A_star,
   }

   # Run the model
   print(f"\nInitializing repair for function '{args.func}' in '{args.model}'...")
   print(f"Complexity: {args.complexity} | Schema: {args.schema}\n")
   print("-" * 50)

   abin = AbinModel(
       function_name=args.func,
       bugged_file_path=args.model,
       test_suite=test_cases,
       max_complexity=args.complexity,
       abduction_schema=schema_map[args.schema],
   )

   repaired_code, behavior, prev_observation, new_observation = (
       abin.start_auto_debugging()
   )

   print("-" * 50)
   if repaired_code:
       print("\n SUCCESSFUL REPAIR! Found candidate fix:")
       print("=" * 40)
       print("\n".join(repaired_code))
       print("=" * 40)
   elif behavior.name == "Valid":
       print("\nNO DEFECT FOUND. All tests passed on the original model.")
   else:
       print("\nUNABLE TO REPAIR. No candidate hypotheses passed the test suite.")


if __name__ == "__main__":
   main()
