# AGENTS.md

This file provides guidance to agentic AI tools (Claude Code, ChatGPT Codex, etc.) when working with code in this repository.

## Commands


### Documentation

Documentation lives in `docs/` apart from `AGENTS.md` and `README.md` that live in the root of the repo. Documentation includes `backlog.md` with list of bugs and future functionality, `changelog.md` with introduced changes, and specifications files.

### Workflow

Before editing the code, perform `git pull`. 
Before starting to implement new feature or a refactoring, ask the user whether you should create a new branch for it. 

After implementing a new feature or doing a major refactoring:
- Add changes to `changelog.md`. 
- If these features or bugs were mentioned in the `backlog.md`, move their description from there to the `changelog.md` and remove them from the `backlog.md`. 
- Re-read README.md and AGENTS.md, update to reflect recent changes.
- Run the tests.
- At the end of the round of changes, ask whether the branch should be merged to main (or to some other branch).
- After each round of editing the code, commit the changes to git and run `git push`.