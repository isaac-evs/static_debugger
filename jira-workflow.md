# Git Workflow & Jira Integration Guide

This repository enforces a naming convention to ensure all code changes are automatically linked to their respective Jira issues. Follow these steps for every feature, task, or bug fix.

## Workflow Steps

### 1. Identify or Create the Jira Ticket
Before moving any code, ensure you have a corresponding ticket in Jira. Note the project key and ticket number (e.g., `ABD-10`).
* **Feature/Task/Bug:** `ABD-*`

### 2. Create and Switch to a New Branch
Always branch off the latest `main`. Your branch name must start with the Jira ticket ID, followed by a short descriptive slug.

```bash
# Fetch latest changes and branch off main
git checkout main
git pull origin main

# Create your feature branch
git checkout -b ABD-10-short-task-description
```

### 3. Commit Your Changes
When committing work, format the commit message so that Jira can track the progress. The Jira ticket ID must be at the beginning of the message.

```bash
git add .
git commit -m "ABD-10 Add implementation for short task description"
```


4. Push and Open a Pull Request (PR)
Push your branch to the remote repository and open a Pull Request targeting the main branch.

Critical: The title of your Pull Request must include the Jira ticket ID (ABD-*).

```bash
# Push branch to remote
git push origin ABD-10-short-task-description
```
